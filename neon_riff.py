#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEON RIFF  -  Juego arcade controlado con un objeto de color frente a la webcam.

Basado en el proyecto original "Juego de Colores" de Giovanni Gabriel Vilca Suelo
(Arquitectura de Computadoras). Version rehecha desde cero:

  * Todos los graficos se dibujan por codigo (no necesita carpeta de imagenes).
  * Estetica synthwave con efecto de brillo neon (bloom).
  * Sonido de guitarra sintetizado (Karplus-Strong) con pygame (opcional).
  * Seguimiento de color calibrable: sirve un objeto de CUALQUIER color.
  * Hilo de camara dedicado, movimiento independiente de los FPS.
  * Combos, multiplicador, modo FEVER, bombas, vidas, niveles y record guardado.

Uso:  python neon_riff.py            (webcam)
      python neon_riff.py --mouse    (sin webcam, controla con el mouse)
"""
import argparse
import json
import math
import os
import random
import threading
import time

import cv2
import numpy as np

try:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    HAVE_PYGAME = True
except Exception:  # pygame es opcional
    HAVE_PYGAME = False

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------
W, H = 960, 540
HORIZON = 300
PLAYER_Y = H - 70
LIVES_MAX = 5
FEVER_TIME = 7.0
NOTES_PER_LEVEL = 12

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(BASE_DIR, "savegame.json")
WINDOW = "NEON RIFF"
FONT = cv2.FONT_HERSHEY_DUPLEX
AA = cv2.LINE_AA


def rgb(r, g, b):
    return (b, g, r)


CYAN = rgb(0, 235, 255)
PINK = rgb(255, 45, 170)
GREEN = rgb(70, 255, 130)
RED = rgb(255, 55, 75)
GOLD = rgb(255, 205, 60)
ORANGE = rgb(255, 140, 40)
PURPLE = rgb(150, 90, 255)
WHITE = (255, 255, 255)
DIM = rgb(160, 160, 200)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lighten(c, k=0.6):
    return tuple(int(v + (255 - v) * k) for v in c)


def scale_color(c, k):
    return tuple(int(clamp(v * k, 0, 255)) for v in c)


# --------------------------------------------------------------------------
# Guardado
# --------------------------------------------------------------------------
def load_save():
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_save(data):
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Sonido (todo sintetizado, sin archivos)
# --------------------------------------------------------------------------
class Audio:
    SCALE = [164.81, 196.00, 220.00, 246.94, 293.66, 329.63,
             392.00, 440.00, 493.88, 587.33, 659.25, 783.99]  # Mi menor pentatonica
    SEQ = list(range(12)) + list(range(10, 0, -1))

    def __init__(self, enabled=True):
        self.ok = False
        self.muted = False
        self.s = {}
        self.sr = 44100
        if not (enabled and HAVE_PYGAME):
            return
        try:
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
            self.sr = pygame.mixer.get_init()[0]
            self._build()
            self.ok = True
        except Exception:
            self.ok = False

    # -- sintesis ----------------------------------------------------------
    def _pluck(self, freq, dur=0.6, vol=0.7, drive=2.5):
        n = int(self.sr * dur)
        period = max(2, int(self.sr / freq))
        cur = np.random.uniform(-1, 1, period)
        out = np.zeros(n)
        for s in range(0, n, period):
            e = min(s + period, n)
            out[s:e] = cur[:e - s]
            cur = 0.5 * (cur + np.roll(cur, -1)) * 0.997
        out = np.tanh(out * drive) * 0.6
        out *= np.minimum(1.0, np.linspace(1, 0, n) * 6)
        return out * vol

    def _mix(self, parts, dur):
        out = np.zeros(int(self.sr * dur))
        for start, sig in parts:
            i = int(start * self.sr)
            seg = sig[:max(0, len(out) - i)]
            out[i:i + len(seg)] += seg
        return out

    def _sound(self, sig):
        sig = np.clip(sig, -1, 1)
        a = (sig * 32767 * 0.8).astype(np.int16)
        st = np.ascontiguousarray(np.column_stack((a, a)))
        return pygame.sndarray.make_sound(st)

    def _build(self):
        for i, f in enumerate(self.SCALE):
            self.s[f"n{i}"] = self._sound(self._pluck(f, 0.55))
        t = np.linspace(0, 0.45, int(self.sr * 0.45), False)
        boom = (np.random.uniform(-1, 1, len(t)) * np.exp(-t * 9) * 0.7
                + np.sin(2 * np.pi * 70 * t) * np.exp(-t * 5) * 0.8)
        self.s["bomb"] = self._sound(boom)
        self.s["miss"] = self._sound(self._pluck(110, 0.35, 0.8, 4.0))
        self.s["gold"] = self._sound(self._mix(
            [(k * 0.06, self._pluck(f, 0.5)) for k, f in
             enumerate((329.63, 392.0, 493.88, 659.25, 783.99))], 0.9))
        self.s["life"] = self._sound(self._mix(
            [(k * 0.08, self._pluck(f, 0.4, 0.6, 1.5)) for k, f in
             enumerate((392.0, 523.25, 659.25))], 0.7))
        self.s["level"] = self._sound(self._mix(
            [(k * 0.07, self._pluck(f, 0.45)) for k, f in
             enumerate((329.63, 392.0, 493.88, 659.25))], 0.8))
        self.s["start"] = self._sound(self._mix(
            [(0.0, self._pluck(164.81, 0.9)), (0.03, self._pluck(246.94, 0.9)),
             (0.06, self._pluck(329.63, 0.9))], 1.0))
        self.s["over"] = self._sound(self._mix(
            [(k * 0.22, self._pluck(f, 1.0, 0.7, 3.5)) for k, f in
             enumerate((196.0, 185.0, 174.6, 146.8))], 1.6))

    def play(self, name):
        if self.ok and not self.muted and name in self.s:
            self.s[name].play()

    def note(self, combo):
        idx = self.SEQ[(max(1, combo) - 1) % len(self.SEQ)]
        self.play(f"n{idx}")


# --------------------------------------------------------------------------
# Camara (hilo propio para no bloquear el juego) y camara falsa para pruebas
# --------------------------------------------------------------------------
class Camera:
    def __init__(self, index=0):
        self.cap = cv2.VideoCapture(index)
        self.ok = bool(self.cap.isOpened())
        self.frame = None
        self.lock = threading.Lock()
        self.running = self.ok
        if self.ok:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            good, f = self.cap.read()
            if good and f is not None:
                f = cv2.flip(f, 1)  # efecto espejo
                with self.lock:
                    self.frame = f
            else:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            return self.frame

    def close(self):
        self.running = False
        time.sleep(0.05)
        try:
            self.cap.release()
        except Exception:
            pass


class FakeCam:
    """Camara sintetica para el autotest (disco de color sobre fondo gris)."""

    def __init__(self):
        self.nx = 0.5
        self.color = (40, 220, 40)
        self.visible = True

    def read(self):
        f = np.full((480, 640, 3), (38, 30, 34), np.uint8)
        if self.visible:
            cv2.circle(f, (int(self.nx * 640), 240), 46, self.color, -1)
        return f

    def close(self):
        pass


# --------------------------------------------------------------------------
# Seguimiento de color en HSV (calibrable, soporta el rojo que "da la vuelta")
# --------------------------------------------------------------------------
class Tracker:
    TOL_H = 14

    def __init__(self, color=None):
        self.center = tuple(color) if color else (60.0, 220.0, 200.0)
        self.k3 = np.ones((3, 3), np.uint8)
        self.k5 = np.ones((5, 5), np.uint8)
        self.min_area = 260
        self.last_mask = None
        self.ranges = []
        self._build()

    def _build(self):
        h, s, v = self.center
        smin = int(max(70, s - 90))
        vmin = int(max(60, v - 110))
        lo, hi = int(h - self.TOL_H), int(h + self.TOL_H)
        rng = []
        if lo < 0:
            rng.append(((0, smin, vmin), (hi, 255, 255)))
            rng.append(((180 + lo, smin, vmin), (179, 255, 255)))
        elif hi > 179:
            rng.append(((lo, smin, vmin), (179, 255, 255)))
            rng.append(((0, smin, vmin), (hi - 180, 255, 255)))
        else:
            rng.append(((lo, smin, vmin), (hi, 255, 255)))
        self.ranges = [(np.array(a, np.uint8), np.array(b, np.uint8)) for a, b in rng]

    @staticmethod
    def cal_box(frame):
        fh, fw = frame.shape[:2]
        r = int(0.07 * fh)
        cx, cy = fw // 2, fh // 2
        return cx - r, cy - r, cx + r, cy + r

    def calibrate(self, frame):
        x0, y0, x1, y1 = self.cal_box(frame)
        roi = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV).reshape(-1, 3)
        sel = roi[(roi[:, 1] > 60) & (roi[:, 2] > 50)]
        if len(sel) < 0.25 * len(roi):
            return False
        ang = sel[:, 0].astype(np.float32) * (2 * math.pi / 180.0)
        h = (math.degrees(math.atan2(np.sin(ang).mean(), np.cos(ang).mean())) / 2.0) % 180
        self.center = (float(h), float(np.median(sel[:, 1])), float(np.median(sel[:, 2])))
        self._build()
        return True

    def detect(self, frame):
        """Devuelve (nx, ny, radio_norm) del objeto mas grande, o None."""
        small = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (5, 5), 0)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = None
        for lo, hi in self.ranges:
            m = cv2.inRange(hsv, lo, hi)
            mask = m if mask is None else cv2.bitwise_or(mask, m)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.k3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.k5)
        self.last_mask = mask
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if area < self.min_area:
            return None
        m = cv2.moments(c)
        if m["m00"] == 0:
            return None
        return (m["m10"] / m["m00"] / 320.0, m["m01"] / m["m00"] / 240.0,
                math.sqrt(area / math.pi) / 320.0)

    def swatch(self):
        h, s, v = self.center
        px = cv2.cvtColor(np.uint8([[[int(h), int(s), int(v)]]]), cv2.COLOR_HSV2BGR)[0, 0]
        return tuple(int(x) for x in px)


# --------------------------------------------------------------------------
# Utilidades de dibujo
# --------------------------------------------------------------------------
_T = np.linspace(0, 2 * np.pi, 40)
_HX = 16 * np.sin(_T) ** 3
_HY = 13 * np.cos(_T) - 5 * np.cos(2 * _T) - 2 * np.cos(3 * _T) - np.cos(4 * _T)


def heart_pts(cx, cy, s):
    pts = np.stack([cx + _HX * s, cy - _HY * s], 1).astype(np.int32)
    return pts.reshape(-1, 1, 2)


def star_pts(cx, cy, ro, ri, rot):
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        a = rot + k * math.pi / 5 - math.pi / 2
        pts.append((int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
    return np.array(pts, np.int32).reshape(-1, 1, 2)


def text(img, s, org, scale=0.6, color=WHITE, th=1, align="left", shadow=True):
    (tw, _), _ = cv2.getTextSize(s, FONT, scale, th)
    x, y = int(org[0]), int(org[1])
    if align == "center":
        x -= tw // 2
    elif align == "right":
        x -= tw
    if shadow:
        cv2.putText(img, s, (x + 2, y + 2), FONT, scale, (0, 0, 0), th + 1, AA)
    cv2.putText(img, s, (x, y), FONT, scale, color, th, AA)


def panel(img, x0, y0, x1, y1, alpha=0.55):
    roi = img[y0:y1, x0:x1]
    img[y0:y1, x0:x1] = cv2.convertScaleAbs(roi, alpha=1 - alpha)


def bloom(canvas, layer):
    """Suma la capa neon + un halo desenfocado (efecto de brillo)."""
    small = cv2.resize(layer, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    glow = cv2.add(cv2.GaussianBlur(small, (0, 0), 2.5), cv2.GaussianBlur(small, (0, 0), 6))
    glow = cv2.resize(glow, (W, H), interpolation=cv2.INTER_LINEAR)
    glow = cv2.convertScaleAbs(glow, alpha=1.6)
    return cv2.add(cv2.add(canvas, layer), glow)


def build_background():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    top = np.array(rgb(14, 0, 40), np.float32)
    hor = np.array(rgb(120, 15, 120), np.float32)
    floor = np.array(rgb(14, 0, 30), np.float32)
    t = np.clip(yy / HORIZON, 0, 1)[..., None] ** 1.6
    sky = top + (hor - top) * t
    img = np.where((yy < HORIZON)[..., None], sky, floor)

    cx, cy, r = W // 2, HORIZON - 8, 108
    inside = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & (yy <= HORIZON)
    k = np.clip((yy - (cy - r)) / (2 * r), 0, 1)[..., None]
    sun = np.array(rgb(255, 225, 90), np.float32) * (1 - k) + np.array(rgb(255, 40, 140), np.float32) * k
    kk = k[..., 0]
    cut = (kk > 0.5) & ((yy % 14) < (kk - 0.5) * 20 + 1)
    inside &= ~cut
    img = np.where(inside[..., None], sun, img)

    halo = np.zeros((H, W, 3), np.float32)
    cv2.circle(halo, (cx, cy), r + 6, rgb(255, 60, 150), -1, AA)
    halo = cv2.GaussianBlur(halo, (0, 0), 38)
    img = img + halo * 0.55

    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    img *= (1 - 0.45 * np.clip(d - 0.35, 0, 1) ** 1.6)[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Elementos del juego
# --------------------------------------------------------------------------
class Item:
    def __init__(self, x, y, kind):
        self.x, self.y, self.kind = x, y, kind
        self.vs = {"note": 1.0, "bomb": 1.05, "gold": 1.25, "heart": 0.9}[kind]
        self.rot = random.uniform(0, 6.28)
        self.spin = random.choice((-1, 1)) * random.uniform(1.5, 3.0)
        self.phase = random.uniform(0, 6.28)


class Game:
    def __init__(self, audio, cam, tracker, save, persist=True):
        self.audio, self.cam, self.tracker = audio, cam, tracker
        self.save, self.persist = save, persist
        self.best = int(save.get("best", 0))
        self.control = "camera" if cam is not None else "mouse"
        self.show_cam = True
        self.state = "MENU"
        self.px = W / 2
        self.mouse_x = W / 2
        self.t = 0.0
        self.scroll = 0.0
        self.det = None
        self.frame = None
        self.last_target = None
        self.lost = 0.0
        self.waiting = False
        self.pulse = self.shake = self.flash = self.vib = 0.0
        self.flash_color = RED
        self.banner = None
        self.calib_msg = None
        self.bg = build_background()
        rng = np.random.default_rng(7)
        self.star_x = rng.integers(0, W, 90)
        self.star_y = rng.integers(0, HORIZON - 40, 90)
        self.star_ph = rng.random(90) * 6.28
        self.star_sp = rng.random(90) * 3 + 1
        self._cores = []
        self.reset()

    # ---------------------------------------------------------------- estado
    def reset(self):
        self.score = 0
        self.lives = LIVES_MAX
        self.combo = 0
        self.max_combo = 0
        self.level = 1
        self.caught = 0
        self.fever = 0.0
        self.items = []
        self.particles = []
        self.popups = []
        self.spawn_t = 0.8
        self.last_kinds = []
        self.last_spawn_x = W / 2
        self.new_best = False

    def start(self):
        self.reset()
        self.state = "PLAYING"
        self.banner = ["A TOCAR!", 1.2, CYAN]
        self.audio.play("start")

    def game_over(self):
        self.state = "GAMEOVER"
        self.new_best = self.score > self.best
        if self.new_best:
            self.best = self.score
            self.save["best"] = self.best
            if self.persist:
                write_save(self.save)
        self.burst(self.px, PLAYER_Y, PINK, 40, 380)
        self.burst(self.px, PLAYER_Y, CYAN, 30, 300)
        self.shake = 1.0
        self.audio.play("over")

    # ------------------------------------------------------------ parametros
    def speed(self):
        return min(640.0, 240.0 + 30.0 * (self.level - 1))

    def interval(self):
        return max(0.32, 0.95 - 0.065 * (self.level - 1))

    def mult(self):
        return 1 + min(7, self.combo // 6)

    def half_width(self):
        return 105 if self.fever > 0 else 80

    # ------------------------------------------------------------------ mundo
    def spawn(self):
        r = random.random()
        p_bomb = min(0.30, 0.10 + 0.02 * self.level)
        if r < 0.05:
            kind = "gold"
        elif r < 0.08 and self.lives < LIVES_MAX:
            kind = "heart"
        elif r < 0.08 + p_bomb:
            kind = "bomb"
        else:
            kind = "note"
        if kind == "bomb" and self.last_kinds[-2:] == ["bomb", "bomb"]:
            kind = "note"
        self.last_kinds.append(kind)
        x = self.last_spawn_x
        for _ in range(6):
            x = random.uniform(70, W - 70)
            if abs(x - self.last_spawn_x) > 130:
                break
        self.last_spawn_x = x
        self.items.append(Item(x, -50, kind))

    def burst(self, x, y, color, n, speed=260):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            s = random.uniform(60, speed)
            life = random.uniform(0.4, 0.9)
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s - 80,
                                   life, life, color, random.uniform(2, 5)])

    def popup(self, s, x, y, color):
        self.popups.append([s, x, y, 0.9, 0.9, color])

    def lose_life(self, x, label, shake, sound):
        self.lives -= 1
        self.combo = 0
        self.shake = max(self.shake, shake)
        self.popup(label, x, PLAYER_Y - 40, RED)
        self.audio.play(sound)
        if self.lives <= 0:
            self.game_over()

    def on_catch(self, it):
        k = it.kind
        if k == "note":
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.caught += 1
            pts = 10 * self.mult() * (2 if self.fever > 0 else 1)
            self.score += pts
            self.burst(it.x, PLAYER_Y - 10, CYAN, 14)
            self.popup(f"+{pts}", it.x, PLAYER_Y - 40, CYAN)
            self.vib, self.pulse = 1.0, 1.0
            self.audio.note(self.combo)
            if self.combo in (10, 25, 50, 100):
                self.banner = [f"{self.combo} COMBO!", 1.3, PINK]
            nl = 1 + self.caught // NOTES_PER_LEVEL
            if nl > self.level:
                self.level = nl
                self.banner = [f"NIVEL {nl}", 1.5, GREEN]
                self.audio.play("level")
        elif k == "gold":
            self.fever = FEVER_TIME
            self.combo += 3
            self.max_combo = max(self.max_combo, self.combo)
            pts = 50 * self.mult()
            self.score += pts
            self.burst(it.x, PLAYER_Y - 10, GOLD, 34, 340)
            self.popup(f"+{pts}", it.x, PLAYER_Y - 40, GOLD)
            self.banner = ["FEVER x2", 1.4, GOLD]
            self.vib, self.pulse = 1.0, 1.0
            self.audio.play("gold")
        elif k == "heart":
            self.lives = min(LIVES_MAX, self.lives + 1)
            self.burst(it.x, PLAYER_Y - 10, PINK, 20)
            self.popup("+1 VIDA", it.x, PLAYER_Y - 40, PINK)
            self.audio.play("life")
        elif k == "bomb":
            self.flash, self.flash_color = 1.0, RED
            self.burst(it.x, PLAYER_Y - 10, RED, 36, 380)
            self.burst(it.x, PLAYER_Y - 10, GOLD, 16, 260)
            self.lose_life(it.x, "-1 VIDA", 1.0, "bomb")

    def update(self, dt, target, tracking):
        self.t += dt
        self.pulse = max(0.0, self.pulse - dt * 3)
        self.shake = max(0.0, self.shake - dt * 2.2)
        self.flash = max(0.0, self.flash - dt * 2.5)
        self.vib = max(0.0, self.vib - dt * 1.8)
        if self.banner:
            self.banner[1] -= dt
            if self.banner[1] <= 0:
                self.banner = None
        if self.calib_msg:
            self.calib_msg[1] -= dt
            if self.calib_msg[1] <= 0:
                self.calib_msg = None

        if target is not None:
            self.px += (target - self.px) * min(1.0, dt * 16)
        self.px = clamp(self.px, 40, W - 40)

        for p in self.particles:
            p[4] -= dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 500 * dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for p in self.popups:
            p[3] -= dt
            p[2] -= 60 * dt
        self.popups = [p for p in self.popups if p[3] > 0]

        self.waiting = self.state == "PLAYING" and not tracking
        self.scroll += dt * (1.2 + (self.speed() / 300.0 if self.state == "PLAYING" else 0.4))
        if self.state != "PLAYING" or self.waiting:
            return

        if self.fever > 0:
            self.fever = max(0.0, self.fever - dt)
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn()
            self.spawn_t = self.interval() * random.uniform(0.75, 1.25)

        spd = self.speed()
        pw = self.half_width()
        keep = []
        for it in self.items:
            it.y += spd * it.vs * dt
            it.rot += it.spin * dt
            if it.y + 14 >= PLAYER_Y - 12 and it.y - 14 <= PLAYER_Y + 14 \
                    and abs(it.x - self.px) <= pw + 10:
                self.on_catch(it)
                if self.state != "PLAYING":
                    return
                continue
            if it.y > H + 40:
                if it.kind == "note":
                    self.lose_life(it.x, "FALLASTE", 0.35, "miss")
                    if self.state != "PLAYING":
                        return
                continue
            keep.append(it)
        self.items = keep

    # --------------------------------------------------------- entrada / paso
    def track(self, frame, dt):
        det = self.tracker.detect(frame) if frame is not None else None
        self.det = det
        if det is not None:
            nx = clamp((det[0] - 0.1) / 0.8, 0.0, 1.0)
            self.last_target = nx * W
            self.lost = 0.0
            return True, self.last_target
        self.lost += dt
        if self.lost < 0.3 and self.last_target is not None:
            return True, self.last_target
        return False, None

    def step(self, dt, frame=None):
        self.frame = frame
        if self.control == "camera":
            tracking, target = self.track(frame, dt)
        else:
            tracking, target = True, self.mouse_x
        self.update(dt, target, tracking)
        return self.render()

    def handle_key(self, key):
        """Devuelve True si hay que salir."""
        if key in (ord("q"), ord("Q")):
            return True
        if key == 27:
            if self.state == "MENU":
                return True
            self.state = "MENU"
        elif key == 32:
            if self.state in ("MENU", "GAMEOVER"):
                self.start()
            elif self.state == "PAUSED":
                self.state = "PLAYING"
            elif self.state == "CALIBRATE":
                self.do_calibrate()
        elif key in (ord("p"), ord("P")):
            if self.state == "PLAYING":
                self.state = "PAUSED"
            elif self.state == "PAUSED":
                self.state = "PLAYING"
        elif key in (ord("r"), ord("R")):
            if self.state in ("PLAYING", "PAUSED", "GAMEOVER"):
                self.start()
        elif key in (ord("c"), ord("C")):
            if self.cam is not None and self.state in ("MENU", "GAMEOVER"):
                self.state = "CALIBRATE"
        elif key in (ord("t"), ord("T")):
            if self.cam is not None:
                self.control = "mouse" if self.control == "camera" else "camera"
        elif key in (ord("m"), ord("M")):
            self.audio.muted = not self.audio.muted
        elif key in (ord("v"), ord("V")):
            self.show_cam = not self.show_cam
        return False

    def do_calibrate(self):
        if self.frame is None:
            self.calib_msg = ["SIN IMAGEN DE CAMARA", 2.5, RED]
            return
        if self.tracker.calibrate(self.frame):
            h, s, v = self.tracker.center
            self.save["color"] = [h, s, v]
            if self.persist:
                write_save(self.save)
            self.calib_msg = ["COLOR GUARDADO", 2.0, GREEN]
            self.state = "MENU"
        else:
            self.calib_msg = ["COLOR POCO VIVO: USA UN OBJETO MAS COLORIDO", 3.0, RED]

    # --------------------------------------------------------------- dibujo
    def neon(self, layer, s, center, scale, color, th=2):
        (tw, tht), _ = cv2.getTextSize(s, FONT, scale, th)
        org = (int(center[0] - tw / 2), int(center[1] + tht / 2))
        cv2.putText(layer, s, org, FONT, scale, color, th + 3, AA)
        self._cores.append((s, org, scale, th, lighten(color, 0.8)))

    def draw_stars(self, layer):
        for i in range(len(self.star_x)):
            b = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.t * self.star_sp[i] + self.star_ph[i]))
            c = (int(255 * b), int(235 * b), int(255 * b))
            cv2.circle(layer, (int(self.star_x[i]), int(self.star_y[i])), 1, c, -1)

    def draw_floor(self, layer):
        col = scale_color(rgb(200, 35, 210), min(1.0, 0.5 + self.pulse * 0.5))
        cx = W // 2
        for i in range(-16, 17):
            cv2.line(layer, (cx, HORIZON), (cx + i * 120, H), col, 1, AA)
        n = 14
        for j in range(n):
            z = ((j + self.scroll) % n) / n
            y = int(HORIZON + (H - HORIZON) * (z ** 2.3))
            cv2.line(layer, (0, y), (W, y), col, 1, AA)
        cv2.line(layer, (0, HORIZON), (W, HORIZON), CYAN, 2, AA)

    def draw_items(self, layer):
        for it in self.items:
            x = int(it.x + 6 * math.sin(self.t * 3 + it.phase))
            y = int(it.y)
            if it.kind == "note":
                cv2.ellipse(layer, (x, y), (14, 10), -20, 0, 360, CYAN, -1, AA)
                cv2.line(layer, (x + 12, y - 4), (x + 12, y - 42), CYAN, 3, AA)
                flag = np.array([(x + 12, y - 42), (x + 22, y - 34),
                                 (x + 28, y - 24), (x + 22, y - 16)], np.int32)
                cv2.polylines(layer, [flag], False, CYAN, 3, AA)
                cv2.ellipse(layer, (x, y), (8, 5), -20, 0, 360, lighten(CYAN, 0.85), -1, AA)
            elif it.kind == "bomb":
                cv2.circle(layer, (x, y), 16, rgb(40, 8, 12), -1, AA)
                cv2.circle(layer, (x, y), 16, RED, 3, AA)
                for k in range(8):
                    a = it.rot + k * math.pi / 4
                    p1 = (int(x + 19 * math.cos(a)), int(y + 19 * math.sin(a)))
                    p2 = (int(x + 29 * math.cos(a)), int(y + 29 * math.sin(a)))
                    cv2.line(layer, p1, p2, RED, 3, AA)
                cv2.line(layer, (x - 7, y - 7), (x + 7, y + 7), lighten(RED, 0.6), 3, AA)
                cv2.line(layer, (x - 7, y + 7), (x + 7, y - 7), lighten(RED, 0.6), 3, AA)
            elif it.kind == "gold":
                pulse = 1 + 0.15 * math.sin(self.t * 8)
                pts = star_pts(x, y, 24 * pulse, 10 * pulse, it.rot)
                cv2.fillPoly(layer, [pts], GOLD, AA)
                cv2.polylines(layer, [pts], True, lighten(GOLD, 0.7), 2, AA)
            elif it.kind == "heart":
                s = 1.15 + 0.1 * math.sin(self.t * 6)
                pts = heart_pts(x, y, s)
                cv2.fillPoly(layer, [pts], PINK, AA)
                cv2.polylines(layer, [pts], True, lighten(PINK, 0.7), 2, AA)

    def draw_particles(self, layer):
        for x, y, _, _, life, mx, color, size in self.particles:
            k = life / mx
            cv2.circle(layer, (int(x), int(y)), max(1, int(size * k)),
                       scale_color(color, k), -1, AA)

    def draw_player(self, layer):
        pw = self.half_width()
        x, y = int(self.px), PLAYER_Y
        col = GOLD if self.fever > 0 else CYAN
        acc = ORANGE if self.fever > 0 else PINK
        cv2.rectangle(layer, (x - pw, y - 10), (x + pw, y + 10), rgb(40, 10, 40), -1)
        cv2.rectangle(layer, (x - pw, y - 10), (x + pw, y + 10), col, 2, AA)
        cv2.rectangle(layer, (x - pw - 26, y - 14), (x - pw, y + 14), acc, 2, AA)
        for k in range(1, 8):
            fx = x - pw + int(k * 2 * pw / 8)
            cv2.line(layer, (fx, y - 10), (fx, y + 10), scale_color(col, 0.45), 1, AA)
        amp = self.vib * 5.0
        u = np.linspace(0, 1, 28)
        for si, off in enumerate((-6, -2, 2, 6)):
            xs = x - pw + u * 2 * pw
            ys = y + off + amp * np.sin(u * np.pi * (si + 1)) * math.sin(self.t * 45 + si)
            pts = np.stack([xs, ys], 1).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(layer, [pts], False, lighten(col, 0.8), 1, AA)
        cv2.line(layer, (x - pw, y + 24), (x + pw, y + 24), scale_color(col, 0.35), 1, AA)

    def draw_hud(self, c):
        text(c, "PUNTOS", (26, 30), 0.5, DIM)
        text(c, f"{self.score:07d}", (24, 68), 1.25, WHITE, 2)
        if self.combo >= 2:
            cc = GOLD if self.fever > 0 else CYAN
            text(c, f"COMBO {self.combo}", (26, 100), 0.7, cc, 1)
            text(c, f"x{self.mult()}", (178, 100), 0.8, GOLD, 2)
        if self.fever > 0:
            cv2.rectangle(c, (26, 112), (206, 122), GOLD, 1, AA)
            cv2.rectangle(c, (26, 112), (26 + int(180 * self.fever / FEVER_TIME), 122), GOLD, -1)
            text(c, "FEVER x2", (214, 123), 0.5, GOLD)
        for i in range(LIVES_MAX):
            x = W - 176 + i * 34
            pts = heart_pts(x, 36, 0.9)
            if i < self.lives:
                cv2.fillPoly(c, [pts], PINK, AA)
            cv2.polylines(c, [pts], True, lighten(PINK, 0.4), 1, AA)
        text(c, f"NIVEL {self.level}", (W - 24, 82), 0.6, GREEN, 1, "right")
        text(c, f"RECORD {self.best}", (W - 24, 106), 0.55, DIM, 1, "right")

    def draw_pip(self, canvas, top_left=False):
        f = self.frame
        if f is None or not self.show_cam or self.cam is None:
            return
        fh, fw = f.shape[:2]
        pw_, ph_ = 200, int(200 * fh / fw)
        pip = cv2.resize(f, (pw_, ph_), interpolation=cv2.INTER_AREA)
        if self.det is not None:
            cv2.circle(pip, (int(self.det[0] * pw_), int(self.det[1] * ph_)),
                       max(4, int(self.det[2] * pw_)), GREEN, 2, AA)
        if top_left:
            x0, y0 = 14, 84
        else:
            x0, y0 = W - pw_ - 14, H - ph_ - 14
        roi = canvas[y0:y0 + ph_, x0:x0 + pw_]
        canvas[y0:y0 + ph_, x0:x0 + pw_] = cv2.addWeighted(roi, 0.25, pip, 0.75, 0)
        cv2.rectangle(canvas, (x0, y0), (x0 + pw_, y0 + ph_), CYAN, 1, AA)

    # ------------------------------------------------------------- render
    def render_calibration(self):
        canvas = np.zeros((H, W, 3), np.uint8)
        canvas[:] = rgb(18, 6, 30)
        f = self.frame
        if f is None:
            text(canvas, "SIN IMAGEN DE CAMARA", (W // 2, H // 2), 0.9, RED, 2, "center")
            return canvas
        fh, fw = f.shape[:2]
        s = min(W / fw, H / fh)
        dw, dh = int(fw * s), int(fh * s)
        ox, oy = (W - dw) // 2, (H - dh) // 2
        canvas[oy:oy + dh, ox:ox + dw] = cv2.resize(f, (dw, dh))
        if self.det is not None:
            cv2.circle(canvas, (int(ox + self.det[0] * dw), int(oy + self.det[1] * dh)),
                       max(6, int(self.det[2] * dw)), GREEN, 2, AA)
        x0, y0, x1, y1 = self.tracker.cal_box(f)
        p0 = (int(ox + x0 * s), int(oy + y0 * s))
        p1 = (int(ox + x1 * s), int(oy + y1 * s))
        cv2.rectangle(canvas, p0, p1, GOLD, 2, AA)
        m = self.tracker.last_mask
        if m is not None:
            mm = cv2.cvtColor(cv2.resize(m, (200, 150)), cv2.COLOR_GRAY2BGR)
            canvas[H - 164:H - 14, 14:214] = mm
            cv2.rectangle(canvas, (14, H - 164), (214, H - 14), CYAN, 1, AA)
            text(canvas, "MASCARA", (18, H - 170), 0.45, DIM)
        panel(canvas, 0, 0, W, 78, 0.6)
        text(canvas, "CALIBRACION DE COLOR", (W // 2, 34), 0.95, CYAN, 2, "center")
        text(canvas, "Pon tu objeto dentro del cuadro dorado y presiona ESPACIO   (ESC = volver)",
             (W // 2, 62), 0.55, WHITE, 1, "center")
        if self.calib_msg:
            text(canvas, self.calib_msg[0], (W // 2, H - 40), 0.8, self.calib_msg[2], 2, "center")
        return canvas

    def render(self):
        if self.state == "CALIBRATE":
            return self.render_calibration()

        self._cores = []
        canvas = self.bg.copy()
        layer = np.zeros_like(canvas)
        ui = np.zeros_like(canvas)
        self.draw_stars(layer)
        self.draw_floor(layer)
        self.draw_items(layer)
        self.draw_particles(layer)
        self.draw_player(layer)
        canvas = bloom(canvas, layer)

        if self.shake > 0:
            a = self.shake * 9
            M = np.float32([[1, 0, random.uniform(-a, a)], [0, 1, random.uniform(-a, a)]])
            canvas = cv2.warpAffine(canvas, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        if self.flash > 0:
            fc = scale_color(self.flash_color, self.flash * 0.35)
            canvas = cv2.add(canvas, (fc[0], fc[1], fc[2], 0))

        if self.state == "GAMEOVER":
            canvas = cv2.convertScaleAbs(canvas, alpha=0.45)
        elif self.state == "PAUSED":
            canvas = cv2.convertScaleAbs(canvas, alpha=0.5)

        # ---- capa de interfaz neon
        if self.state == "MENU":
            self.neon(ui, "NEON RIFF", (W // 2, 112), 2.9, PINK, 4)
            self.neon(ui, "ARCADE DE COLORES", (W // 2, 168), 0.9, CYAN, 1)
        elif self.state == "GAMEOVER":
            self.neon(ui, "GAME OVER", (W // 2, 140), 2.5, RED, 4)
        elif self.state == "PAUSED":
            self.neon(ui, "PAUSA", (W // 2, 200), 2.2, CYAN, 3)
        if self.banner and self.state == "PLAYING":
            k = min(1.0, self.banner[1] * 2.5)
            self.neon(ui, self.banner[0], (W // 2, 210), 1.6, scale_color(self.banner[2], k), 3)
        canvas = bloom(canvas, ui)
        for s, org, scale, th, col in self._cores:
            cv2.putText(canvas, s, org, FONT, scale, col, th, AA)

        # ---- texto nitido
        if self.state == "MENU":
            panel(canvas, 90, 316, W - 90, 452, 0.6)
            text(canvas, "MUEVE UN OBJETO DE COLOR FRENTE A LA CAMARA PARA MOVER TU GUITARRA",
                 (W // 2, 342), 0.55, WHITE, 1, "center")
            text(canvas, "ATRAPA LAS NOTAS    ESQUIVA LAS BOMBAS    TOMA LA ESTRELLA PARA FEVER",
                 (W // 2, 370), 0.55, CYAN, 1, "center")
            text(canvas, "SI FALLAS UNA NOTA O TOCAS UNA BOMBA, PIERDES UNA VIDA",
                 (W // 2, 396), 0.5, DIM, 1, "center")
            if int(self.t * 2) % 2 == 0:
                text(canvas, "PRESIONA ESPACIO PARA JUGAR", (W // 2, 436), 0.85, GOLD, 2, "center")
            text(canvas, "C CALIBRAR COLOR | T CAMARA/MOUSE | M SONIDO | V VISTA CAMARA | "
                         "F PANTALLA COMPLETA | Q SALIR", (W // 2, H - 12), 0.4, DIM, 1, "center")
            text(canvas, f"RECORD {self.best}", (W - 24, 34), 0.6, GOLD, 1, "right")
            if self.cam is not None:
                cv2.circle(canvas, (36, 34), 11, self.tracker.swatch(), -1, AA)
                cv2.circle(canvas, (36, 34), 11, WHITE, 1, AA)
                text(canvas, "TU COLOR", (56, 40), 0.5, DIM)
            mode = "CONTROL: CAMARA" if self.control == "camera" else "CONTROL: MOUSE"
            if self.cam is None:
                mode += "  (NO SE ENCONTRO CAMARA)"
            text(canvas, mode, (26, 64), 0.45, DIM)
            if self.calib_msg:
                text(canvas, self.calib_msg[0], (W // 2, 300), 0.8, self.calib_msg[2], 2, "center")
        elif self.state in ("PLAYING", "PAUSED"):
            self.draw_hud(canvas)
            for s, x, y, life, mx, color in self.popups:
                text(canvas, s, (x, y), 0.7, scale_color(color, min(1.0, life / 0.4)), 2, "center")
            if self.waiting and int(self.t * 2) % 2 == 0:
                panel(canvas, 0, 230, W, 320, 0.6)
                text(canvas, "MUESTRA TU OBJETO DE COLOR", (W // 2, 272), 0.95, GOLD, 2, "center")
                text(canvas, "EL JUEGO ESTA EN PAUSA HASTA QUE TE VEA", (W // 2, 304), 0.55, DIM, 1, "center")
            if self.state == "PAUSED":
                text(canvas, "P = CONTINUAR    R = REINICIAR    ESC = MENU", (W // 2, 300), 0.7, WHITE, 1, "center")
        elif self.state == "GAMEOVER":
            text(canvas, f"PUNTOS  {self.score}", (W // 2, 240), 1.1, WHITE, 2, "center")
            if self.new_best:
                text(canvas, "NUEVO RECORD!", (W // 2, 282), 0.9, GOLD, 2, "center")
            else:
                text(canvas, f"RECORD  {self.best}", (W // 2, 282), 0.8, DIM, 1, "center")
            text(canvas, f"MEJOR COMBO {self.max_combo}     NOTAS {self.caught}     NIVEL {self.level}",
                 (W // 2, 326), 0.7, CYAN, 1, "center")
            if int(self.t * 2) % 2 == 0:
                text(canvas, "ESPACIO O R = REINTENTAR      ESC = MENU", (W // 2, 400), 0.75, GOLD, 1, "center")

        self.draw_pip(canvas, top_left=self.state in ("MENU", "GAMEOVER"))
        return canvas


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def make_mouse_callback(game):
    def cb(event, x, y, flags, param):
        try:
            _, _, ww, _ = cv2.getWindowImageRect(WINDOW)
            if ww > 0:
                x = x * W / ww
        except Exception:
            pass
        game.mouse_x = clamp(float(x), 0, W)
    return cb


def run(args):
    save = load_save()
    cam = None
    if not args.mouse:
        cam = Camera(args.camera)
        if not cam.ok:
            print("No se pudo abrir la camara: modo mouse.")
            cam = None
    audio = Audio(enabled=not args.mute)
    tracker = Tracker(save.get("color"))
    game = Game(audio, cam, tracker, save)

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, W, H)
    cv2.setMouseCallback(WINDOW, make_mouse_callback(game))
    fullscreen = args.fullscreen
    if fullscreen:
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    last = time.perf_counter()
    frames = 0
    try:
        while True:
            now = time.perf_counter()
            dt = min(0.05, now - last)
            last = now
            frame = cam.read() if cam is not None else None
            cv2.imshow(WINDOW, game.step(dt, frame))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("f"), ord("F")):
                fullscreen = not fullscreen
                cv2.setWindowProperty(
                    WINDOW, cv2.WND_PROP_FULLSCREEN,
                    cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
            elif game.handle_key(key):
                break
            frames += 1
            if frames > 10:
                try:
                    if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    pass
            spare = 1 / 62 - (time.perf_counter() - now)
            if spare > 0:
                time.sleep(spare)
    finally:
        if cam is not None:
            cam.close()
        cv2.destroyAllWindows()


# --------------------------------------------------------------------------
# Autotest sin ventana ni camara (usa una camara falsa y un "bot")
# --------------------------------------------------------------------------
def selftest(outdir):
    os.makedirs(outdir, exist_ok=True)
    random.seed(3)

    # 1) el rojo (que da la vuelta en HSV) debe calibrarse y detectarse
    red = np.full((480, 640, 3), (38, 30, 34), np.uint8)
    cv2.circle(red, (320, 240), 60, (0, 0, 230), -1)
    tr = Tracker()
    assert tr.calibrate(red), "no calibro el rojo"
    assert tr.detect(red) is not None, "no detecta el rojo"
    print("rojo OK, hue =", round(tr.center[0], 1))

    cam = FakeCam()
    game = Game(Audio(), cam, Tracker(), {}, persist=False)
    dt = 1 / 60

    def shot(name):
        cv2.imwrite(os.path.join(outdir, name), game.render())

    for _ in range(40):
        game.step(dt, cam.read())
    shot("01_menu.png")

    game.state = "CALIBRATE"
    game.step(dt, cam.read())
    cv2.imwrite(os.path.join(outdir, "02_calibracion.png"), game.render())
    game.handle_key(32)
    assert game.state == "MENU" and game.calib_msg[0] == "COLOR GUARDADO", "calibracion fallo"
    print("calibracion OK")

    game.start()
    shots = {600: "03_juego_a.png", 1500: "04_juego_b.png", 2400: "05_juego_c.png"}
    n = 0
    while game.state == "PLAYING" and n < 6000:
        good = [i for i in game.items if i.kind != "bomb"]
        if good:
            tgt = max(good, key=lambda i: i.y).x
            cam.nx = 0.1 + 0.8 * (tgt / W)
        game.step(dt, cam.read())
        n += 1
        if n in shots:
            shot(shots[n])
    print("bot: pasos", n, "puntos", game.score, "nivel", game.level,
          "mejor combo", game.max_combo, "estado", game.state)

    # perdida de tracking pausa el mundo
    game.start()
    cam.visible = False
    for _ in range(60):
        game.step(dt, cam.read())
    assert game.waiting, "debio quedar en espera"
    shot("06_espera.png")
    cam.visible = True

    # bomba directa + game over
    game.start()
    game.items = [Item(game.px, PLAYER_Y - 5, "bomb")]
    game.step(dt, cam.read())
    assert game.lives == LIVES_MAX - 1, "la bomba no quito vida"
    game.lives = 1
    game.items = [Item(game.px, PLAYER_Y - 5, "bomb")]
    game.step(dt, cam.read())
    assert game.state == "GAMEOVER"
    for _ in range(30):
        game.step(dt, cam.read())
    shot("07_gameover.png")
    print("AUTOTEST OK")


def main():
    ap = argparse.ArgumentParser(description="NEON RIFF - arcade de colores con webcam")
    ap.add_argument("--camera", type=int, default=0, help="indice de la camara (0 por defecto)")
    ap.add_argument("--mouse", action="store_true", help="jugar con el mouse, sin camara")
    ap.add_argument("--mute", action="store_true", help="sin sonido")
    ap.add_argument("--fullscreen", action="store_true", help="pantalla completa")
    ap.add_argument("--selftest", metavar="DIR", help="prueba automatica sin ventana")
    args = ap.parse_args()
    if args.selftest:
        selftest(args.selftest)
    else:
        run(args)


if __name__ == "__main__":
    main()

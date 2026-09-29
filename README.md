# NEON RIFF

Videojuego arcade desarrollado en Python que utiliza la cámara web y visión por computadora para controlar una guitarra virtual mediante el movimiento de un objeto de color. El objetivo es atrapar notas, esquivar obstáculos y conseguir la mayor puntuación posible.

**Curso:** Arquitectura de Computadoras
**Autor:** Giovanni Gabriel Vilca Suelo
**Proyecto original:** Juego de Colores
**Video del proyecto original:** [Ver en YouTube](https://www.youtube.com/watch?v=YUPXOoM4MPQ)

## Tecnologías utilizadas

* Python
* OpenCV
* Pygame (opcional, para el sonido)
* NumPy
* Visión por computadora
* Detección de colores mediante el espacio HSV

## Instalación

Clona el repositorio e instala las dependencias:

```bash
pip install -r requirements.txt
```

Ejecuta el juego:

```bash
python neon_riff.py
```

Pygame es opcional. Sin esta biblioteca, el juego funciona, pero no tiene sonido.

### Modos y opciones

* `--mouse`: jugar sin webcam, utilizando el mouse.
* `--camera N`: seleccionar una cámara.
* `--mute`: silenciar el juego.
* `--fullscreen`: iniciar en pantalla completa.

## Cómo se juega

Controla la guitarra moviendo un objeto de color frente a la cámara.

* **Notas cian:** atrápalas para conseguir puntos y aumentar el combo.
* **Bombas rojas:** evítalas, ya que al tocarlas pierdes una vida.
* **Estrella dorada:** activa el modo FEVER durante 7 segundos, aumenta el ancho de la guitarra y duplica los puntos.
* **Corazón rosa:** recupera una vida.
* **Notas perdidas:** si una nota cae al suelo, pierdes una vida. Comienzas con 5 vidas.

Cada 6 notas consecutivas aumenta el multiplicador, hasta un máximo de x8. Cada 12 notas se incrementa el nivel y aumenta la velocidad del juego.

Si la cámara deja de detectar el objeto, el juego se pausa automáticamente.

## Controles

| Tecla   | Acción                                   |
| ------- | ---------------------------------------- |
| ESPACIO | Jugar, continuar o confirmar calibración |
| P       | Pausar                                   |
| R       | Reiniciar                                |
| C       | Calibrar el color del objeto             |
| T       | Cambiar entre cámara y mouse             |
| M       | Silenciar                                |
| V       | Mostrar u ocultar la vista de cámara     |
| F       | Activar pantalla completa                |
| ESC     | Volver al menú o salir                   |
| Q       | Salir                                    |

## Calibración de color

El juego permite utilizar objetos de distintos colores. Desde el menú, presiona **C**, coloca el objeto dentro del cuadro dorado y presiona **ESPACIO** para calibrarlo.

La calibración se guarda en `savegame.json`, junto con el récord del jugador.

Para obtener mejores resultados, utiliza buena iluminación y un objeto que contraste con el fondo. Evita que otros objetos del mismo color aparezcan en la cámara.

## Mejoras respecto a la versión original

* Eliminación de la dependencia de la carpeta `image/`: los elementos gráficos se generan mediante código y efectos neón.
* Captura de cámara en un hilo independiente para mejorar la fluidez.
* Detección de colisiones mediante solapamiento real.
* Posicionamiento de la guitarra centrado en el objeto detectado.
* Detección del color rojo mediante un rango HSV doble.
* Calibración adaptable a distintos colores.
* Incorporación de vidas, combos, multiplicadores, FEVER, bombas, corazones, niveles y récords.
* Sonido de guitarra sintetizado con una escala pentatónica que cambia según el combo.
* Velocidad del juego independiente de los FPS.
* Organización del código mediante clases y estados.

## Autor

**Giovanni Gabriel Vilca Suelo**
Estudiante de Ingeniería de Sistemas.

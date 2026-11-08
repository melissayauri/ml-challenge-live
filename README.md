# ML Challenge Live

Aplicación educativa de preguntas para **Fundamentos de IA y Programación**, semanas 13 y 14.

Incluye 50 preguntas de aprendizaje supervisado, regresión lineal, clasificación y evaluación de modelos.

## Funcionalidades
- Estudiantes: ingresar mediante QR/código y alias, responder desde el celular.
- Docente: abrir y cerrar votaciones, pausar, revelar manualmente la solución, avanzar, ver barras de resultados y ranking final.
- Cada respuesta correcta aporta 100 puntos; la velocidad no suma puntos.

## Publicación con Render
Este proyecto se publica como **servicio web Python**, no como sitio estático, porque necesita un servidor compartido para los votos.

1. En Render, vincular este repositorio y desplegar con `render.yaml`.
2. Configurar la variable secreta de entorno `ML_TEACHER_PASSWORD` antes del primer despliegue.
3. Abrir el URL HTTPS de Render, acceder como docente y mostrar el QR a los estudiantes.

**Uso de prueba:** el estado de la sesión y los votos residen en memoria. Se pierden al reiniciar o al suspenderse el servidor. No usar como evaluación formal sin persistencia y protección adicional de identidades.

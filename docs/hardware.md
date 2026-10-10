# Hardware

The original build used a Raspberry Pi 4, a 7-inch 800×480 DSI capacitive touchscreen, and an ESP32 / ESP-WROOM-32 board with CP2102 USB-UART.

Check the display with `wlr-randr`. The tested panel reported 800×480 at scale 1.0.

pokeldn handles the ESP32 protocol. TradeBox launches pokeldn and optionally toggles RTS on the serial device to reset the board.

For portable builds, use a stable Pi-compatible power source and shut the Pi down cleanly before removing power.

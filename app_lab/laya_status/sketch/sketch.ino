#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>

Arduino_LED_Matrix matrix;
uint8_t pixels[104] = {};
int statusCode = 0;  // idle, receiving, working, success, error
unsigned long statusSince = 0;
unsigned long lastFrame = 0;

void pixel(int x, int y) {
  if (x >= 0 && x < 13 && y >= 0 && y < 8) pixels[y * 13 + x] = 1;
}

void icon(const char *rows[8]) {
  for (int y = 0; y < 8; ++y) {
    for (int x = 0; x < 13; ++x) {
      if (rows[y][x] == '#') pixel(x, y);
    }
  }
}

void layaStatus(int code) {
  if (code >= 0 && code <= 4) {
    statusCode = code;
    statusSince = millis();
  }
}

void setup() {
  matrix.begin();
  matrix.setGrayscaleBits(1);
  Bridge.begin();
  Bridge.provide_safe("laya_status", layaStatus);
  statusSince = millis();
}

void loop() {
  unsigned long now = millis();
  unsigned long elapsed = now - statusSince;
  if (statusCode == 3 && elapsed >= 1300) statusCode = 0;
  if (statusCode == 4 && elapsed >= 2400) statusCode = 0;
  if (now - lastFrame < 80) return;
  lastFrame = now;
  memset(pixels, 0, sizeof(pixels));

  if (statusCode == 0) {  // a resting heart with a soft beat
    const char *heart[8] = {
      ".............", "...##...##...", "..#..#.#..#..", "..#...#...#..",
      "...#.....#...", "....#...#....", ".....#.#.....", "......#......"
    };
    if (elapsed % 1800 < 1350) icon(heart);
  } else if (statusCode == 1) {  // incoming message moves toward the center
    int shift = (elapsed / 100) % 10;
    for (int y = 2; y <= 5; ++y) pixel(shift, y);
    pixel(shift + 1, 3);
    pixel(shift + 1, 4);
    pixel(shift + 2, 3);
    pixel(shift + 2, 4);
  } else if (statusCode == 2) {  // scanning line while Laya thinks
    int scan = (elapsed / 110) % 13;
    for (int y = 0; y < 8; ++y) pixel(scan, y);
    pixel(4, 3); pixel(5, 3); pixel(7, 3); pixel(8, 3);
    pixel(4, 4); pixel(5, 4); pixel(7, 4); pixel(8, 4);
  } else if (statusCode == 3) {
    const char *check[8] = {
      ".............", ".........#...", "........##...", "..#....##....",
      "..##..##.....", "...####......", "....##.......", "............."
    };
    icon(check);
  } else {  // error
    const char *cross[8] = {
      ".............", "..##.....##..", "...##...##...", "....##.##....",
      ".....###.....", "....##.##....", "...##...##...", "..##.....##.."
    };
    if ((elapsed / 180) % 2 == 0) icon(cross);
  }
  matrix.draw(pixels);
}

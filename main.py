import math
import random
import sys

import pygame


WIDTH = 1280
HEIGHT = 720
FPS = 64

LOW_RES_WIDTH = 320
LOW_RES_HEIGHT = 180

FOV = math.radians(70)
HORIZON = LOW_RES_HEIGHT // 2 - 8
VIEW_DISTANCE = 115
CAMERA_HEIGHT = 10.0
TURN_SPEED = 1.8
MOVE_SPEED = 22.0
JUMP_VELOCITY = 12.5
GRAVITY = 30.0
TREE_COUNT = 120
TREE_AREA_RADIUS = 220.0

SKY_TOP = (110, 156, 209)
SKY_BOTTOM = (181, 214, 238)


class SeededTerrain:
    def __init__(self, seed_text: str):
        self.seed_text = seed_text
        self.seed_value = self._hash_seed(seed_text)

    @staticmethod
    def _hash_seed(seed_text: str) -> int:
        h = 2166136261
        for char in seed_text:
            h ^= ord(char)
            h = (h * 16777619) & 0xFFFFFFFF
        return h

    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    def _value_noise(self, x: float, z: float, scale: float, salt: int) -> float:
        px = x / scale
        pz = z / scale
        x0 = math.floor(px)
        z0 = math.floor(pz)
        xf = px - x0
        zf = pz - z0

        def corner(ix: int, iz: int) -> float:
            n = (ix * 374761393 + iz * 668265263 + self.seed_value + salt * 362437) & 0xFFFFFFFF
            n ^= (n >> 13)
            n = (n * 1274126177) & 0xFFFFFFFF
            n ^= (n >> 16)
            return n / 0xFFFFFFFF

        n00 = corner(x0, z0)
        n10 = corner(x0 + 1, z0)
        n01 = corner(x0, z0 + 1)
        n11 = corner(x0 + 1, z0 + 1)

        u = self._smoothstep(xf)
        v = self._smoothstep(zf)

        nx0 = n00 + (n10 - n00) * u
        nx1 = n01 + (n11 - n01) * u
        return nx0 + (nx1 - nx0) * v

    def height(self, x: float, z: float) -> float:
        h1 = self._value_noise(x, z, 24.0, 1)
        h2 = self._value_noise(x, z, 52.0, 2)
        h3 = self._value_noise(x, z, 112.0, 3)

        combined = h1 * 0.55 + h2 * 0.3 + h3 * 0.15
        ridge = abs(self._value_noise(x, z, 40.0, 4) - 0.5) * 2.0
        combined = combined * 0.75 + ridge * 0.25

        return combined * 24.0

    def ground_color(self, h: float, dist: float) -> tuple[int, int, int]:
        shade = max(0.2, 1.0 - dist / VIEW_DISTANCE)
        if h < 7.0:
            base = (82, 156, 92)
        elif h < 14.0:
            base = (71, 132, 73)
        else:
            base = (118, 124, 111)

        return (
            int(base[0] * shade),
            int(base[1] * shade),
            int(base[2] * shade),
        )


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Legend of the Knight - pygame-ce")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()

        self.world_surface = pygame.Surface((LOW_RES_WIDTH, LOW_RES_HEIGHT))
        self.sky_surface = self.build_sky_surface()

        self.font_title = pygame.font.SysFont("georgia", 56, bold=True)
        self.font_ui = pygame.font.SysFont("consolas", 22)
        self.font_small = pygame.font.SysFont("consolas", 18)

        self.running = True
        self.mode = "start"

        self.seed_text = ""
        self.seed_error = ""

        self.player_x = 0.0
        self.player_z = 0.0
        self.player_yaw = 0.0
        self.jump_offset = 0.0
        self.vertical_velocity = 0.0
        self.is_grounded = True

        self.active_slot = 0
        self.inventory_slots = [None] * 8
        self.armor_slots = [None] * 4
        self.logs = 0
        self.saplings = 0
        self.trees = []
        self.action_message = ""
        self.action_message_timer = 0.0

        self.terrain = SeededTerrain(self.generate_seed())
        self.generate_trees()

    @staticmethod
    def generate_seed() -> str:
        return "".join(str(random.randint(0, 9)) for _ in range(8))

    def validate_seed(self, text: str) -> tuple[bool, str]:
        if text == "":
            return True, self.generate_seed()
        if not text.isdigit():
            return False, "Seed must be numeric"
        if len(text) != 8:
            return False, "Seed must be exactly 8 digits"
        return True, text

    def start_game(self):
        valid, result = self.validate_seed(self.seed_text)
        if not valid:
            self.seed_error = result
            return

        self.seed_text = result
        self.seed_error = ""
        self.terrain = SeededTerrain(self.seed_text)
        self.generate_trees()

        self.player_x = 0.0
        self.player_z = 0.0
        self.player_yaw = 0.0
        self.jump_offset = 0.0
        self.vertical_velocity = 0.0
        self.is_grounded = True
        self.logs = 0
        self.saplings = 0
        self.action_message = ""
        self.action_message_timer = 0.0

        self.mode = "play"

    def handle_start_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self.start_game()
            elif event.key == pygame.K_BACKSPACE:
                self.seed_text = self.seed_text[:-1]
            elif event.unicode.isdigit() and len(self.seed_text) < 8:
                self.seed_text += event.unicode
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            button_rect = self.start_button_rect()
            if button_rect.collidepoint(event.pos):
                self.start_game()

    def handle_play_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            if pygame.K_1 <= event.key <= pygame.K_8:
                self.active_slot = event.key - pygame.K_1
            elif event.key == pygame.K_SPACE and self.is_grounded:
                self.vertical_velocity = JUMP_VELOCITY
                self.is_grounded = False
            elif event.key == pygame.K_f:
                self.punch_tree()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.punch_tree()

    def start_button_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(w // 2 - 170, h // 2 + 74, 340, 56)

    def update_player(self, dt: float):
        keys = pygame.key.get_pressed()

        if keys[pygame.K_a]:
            self.player_yaw -= TURN_SPEED * dt
        if keys[pygame.K_d]:
            self.player_yaw += TURN_SPEED * dt

        forward_x = math.sin(self.player_yaw)
        forward_z = math.cos(self.player_yaw)

        move = 0.0
        if keys[pygame.K_w]:
            move += 1.0
        if keys[pygame.K_s]:
            move -= 1.0

        self.player_x += forward_x * move * MOVE_SPEED * dt
        self.player_z += forward_z * move * MOVE_SPEED * dt

        if not self.is_grounded:
            self.jump_offset += self.vertical_velocity * dt
            self.vertical_velocity -= GRAVITY * dt

            if self.jump_offset <= 0.0:
                self.jump_offset = 0.0
                self.vertical_velocity = 0.0
                self.is_grounded = True

        if self.action_message_timer > 0.0:
            self.action_message_timer = max(0.0, self.action_message_timer - dt)

    def generate_trees(self):
        rng = random.Random(self.terrain.seed_value ^ 0x6C8E9CF5)
        trees = []

        attempts = 0
        max_attempts = TREE_COUNT * 6
        while len(trees) < TREE_COUNT and attempts < max_attempts:
            attempts += 1
            tx = rng.uniform(-TREE_AREA_RADIUS, TREE_AREA_RADIUS)
            tz = rng.uniform(-TREE_AREA_RADIUS, TREE_AREA_RADIUS)

            if tx * tx + tz * tz > TREE_AREA_RADIUS * TREE_AREA_RADIUS:
                continue

            if tx * tx + tz * tz < 18.0 * 18.0:
                continue

            nearby = False
            for tree in trees:
                dx = tree["x"] - tx
                dz = tree["z"] - tz
                if dx * dx + dz * dz < 7.0 * 7.0:
                    nearby = True
                    break
            if nearby:
                continue

            trees.append(
                {
                    "x": tx,
                    "z": tz,
                    "trunk": rng.uniform(10.0, 15.0),
                    "crown": rng.uniform(3.8, 5.8),
                    "alive": True,
                }
            )

        self.trees = trees

    @staticmethod
    def wrap_angle(angle: float) -> float:
        while angle > math.pi:
            angle -= math.tau
        while angle < -math.pi:
            angle += math.tau
        return angle

    def punch_tree(self):
        best_tree = None
        best_distance = 1e9

        for tree in self.trees:
            if not tree["alive"]:
                continue

            dx = tree["x"] - self.player_x
            dz = tree["z"] - self.player_z
            distance = math.hypot(dx, dz)
            if distance > 10.0:
                continue

            target_angle = math.atan2(dx, dz)
            rel_angle = self.wrap_angle(target_angle - self.player_yaw)
            if abs(rel_angle) > math.radians(16):
                continue

            if distance < best_distance:
                best_distance = distance
                best_tree = tree

        if best_tree is None:
            self.action_message = "Punch missed"
            self.action_message_timer = 1.0
            return

        best_tree["alive"] = False
        logs = random.randint(1, 5)
        saplings = random.randint(1, 3)
        self.logs += logs
        self.saplings += saplings
        self.action_message = f"Collected {logs} logs and {saplings} saplings"
        self.action_message_timer = 1.8

    def build_sky_surface(self) -> pygame.Surface:
        surface = pygame.Surface((LOW_RES_WIDTH, LOW_RES_HEIGHT))
        for y in range(LOW_RES_HEIGHT):
            t = y / max(1, LOW_RES_HEIGHT - 1)
            color = (
                int(SKY_TOP[0] + (SKY_BOTTOM[0] - SKY_TOP[0]) * t),
                int(SKY_TOP[1] + (SKY_BOTTOM[1] - SKY_TOP[1]) * t),
                int(SKY_TOP[2] + (SKY_BOTTOM[2] - SKY_TOP[2]) * t),
            )
            pygame.draw.line(surface, color, (0, y), (LOW_RES_WIDTH, y))
        return surface

    def draw_terrain(self):
        self.world_surface.blit(self.sky_surface, (0, 0))

        for sx in range(LOW_RES_WIDTH):
            ray_angle = self.player_yaw + (sx / LOW_RES_WIDTH - 0.5) * FOV
            dx = math.sin(ray_angle)
            dz = math.cos(ray_angle)

            max_y = LOW_RES_HEIGHT
            distance = 1.0
            while distance < VIEW_DISTANCE and max_y > 0:
                wx = self.player_x + dx * distance
                wz = self.player_z + dz * distance

                ground_h = self.terrain.height(wx, wz)
                current_camera_height = CAMERA_HEIGHT + self.jump_offset
                projected = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
                projected = max(0, min(LOW_RES_HEIGHT - 1, projected))

                if projected < max_y:
                    color = self.terrain.ground_color(ground_h, distance)
                    pygame.draw.line(self.world_surface, color, (sx, projected), (sx, max_y))
                    max_y = projected

                distance += 1.1

    def draw_trees(self):
        current_camera_height = CAMERA_HEIGHT + self.jump_offset
        visible_trees = []

        for tree in self.trees:
            if not tree["alive"]:
                continue

            dx = tree["x"] - self.player_x
            dz = tree["z"] - self.player_z
            distance = math.hypot(dx, dz)

            if distance <= 2.0 or distance > VIEW_DISTANCE:
                continue

            angle = math.atan2(dx, dz)
            rel_angle = self.wrap_angle(angle - self.player_yaw)
            if abs(rel_angle) > FOV * 0.6:
                continue

            visible_trees.append((distance, rel_angle, tree))

        visible_trees.sort(reverse=True, key=lambda item: item[0])

        for distance, rel_angle, tree in visible_trees:
            sx = int((rel_angle / FOV + 0.5) * LOW_RES_WIDTH)
            if sx < -8 or sx > LOW_RES_WIDTH + 8:
                continue

            ground_h = self.terrain.height(tree["x"], tree["z"])
            trunk_top_h = ground_h + tree["trunk"]
            crown_top_h = trunk_top_h + tree["crown"]

            trunk_bottom_y = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
            trunk_top_y = HORIZON - int((trunk_top_h - current_camera_height) * 85.0 / distance)
            crown_top_y = HORIZON - int((crown_top_h - current_camera_height) * 85.0 / distance)

            trunk_bottom_y = max(0, min(LOW_RES_HEIGHT - 1, trunk_bottom_y))
            trunk_top_y = max(0, min(LOW_RES_HEIGHT - 1, trunk_top_y))
            crown_top_y = max(0, min(LOW_RES_HEIGHT - 1, crown_top_y))

            trunk_half_width = max(1, int(9.0 / distance))
            for x in range(sx - trunk_half_width, sx + trunk_half_width + 1):
                if 0 <= x < LOW_RES_WIDTH and trunk_top_y < trunk_bottom_y:
                    pygame.draw.line(self.world_surface, (98, 63, 42), (x, trunk_top_y), (x, trunk_bottom_y))

            crown_radius = max(2, int(18.0 / distance))
            crown_center_y = min(LOW_RES_HEIGHT - 1, trunk_top_y)
            pygame.draw.circle(self.world_surface, (56, 131, 54), (sx, crown_center_y), crown_radius)
            pygame.draw.circle(self.world_surface, (66, 150, 61), (sx, max(0, crown_top_y)), max(1, crown_radius - 1))

    def draw_crosshair(self):
        w, h = self.screen.get_size()
        cx = w // 2
        cy = h // 2
        color = (245, 245, 245)
        pygame.draw.line(self.screen, color, (cx - 10, cy), (cx + 10, cy), 2)
        pygame.draw.line(self.screen, color, (cx, cy - 10), (cx, cy + 10), 2)

    def draw_inventory_hud(self):
        w, h = self.screen.get_size()
        slot_size = 52
        gap = 8

        total_w = slot_size * 8 + gap * 7
        start_x = w // 2 - total_w // 2
        y = h - 74

        for i in range(8):
            rect = pygame.Rect(start_x + i * (slot_size + gap), y, slot_size, slot_size)
            fill = (24, 33, 43)
            border = (170, 185, 204)
            if i == self.active_slot:
                border = (241, 182, 60)
                fill = (43, 51, 28)
            pygame.draw.rect(self.screen, fill, rect, border_radius=6)
            pygame.draw.rect(self.screen, border, rect, width=2, border_radius=6)

            label = self.font_small.render(str(i + 1), True, (230, 235, 242))
            self.screen.blit(label, (rect.x + 20, rect.y + 16))

        armor_total = slot_size * 4 + gap * 3
        armor_x = w // 2 - armor_total // 2
        armor_y = y - slot_size - 12

        names = ["H", "C", "L", "B"]
        for i in range(4):
            rect = pygame.Rect(armor_x + i * (slot_size + gap), armor_y, slot_size, slot_size)
            pygame.draw.rect(self.screen, (30, 30, 38), rect, border_radius=6)
            pygame.draw.rect(self.screen, (145, 151, 168), rect, width=2, border_radius=6)
            label = self.font_small.render(names[i], True, (210, 218, 230))
            self.screen.blit(label, (rect.x + 19, rect.y + 16))

    def draw_start_screen(self):
        w, h = self.screen.get_size()
        self.screen.fill((12, 18, 24))

        title = self.font_title.render("Legend of the Knight", True, (238, 240, 245))
        self.screen.blit(title, (w // 2 - title.get_width() // 2, h // 2 - 180))

        subtitle = self.font_ui.render("Enter an 8-digit seed (optional)", True, (206, 214, 227))
        self.screen.blit(subtitle, (w // 2 - subtitle.get_width() // 2, h // 2 - 120))

        input_rect = pygame.Rect(w // 2 - 170, h // 2 - 70, 340, 54)
        pygame.draw.rect(self.screen, (24, 30, 38), input_rect, border_radius=7)
        pygame.draw.rect(self.screen, (130, 143, 164), input_rect, width=2, border_radius=7)

        seed_label = self.seed_text if self.seed_text else "Type numbers only"
        seed_color = (245, 246, 248) if self.seed_text else (145, 158, 174)
        text = self.font_ui.render(seed_label, True, seed_color)
        self.screen.blit(text, (input_rect.x + 12, input_rect.y + 14))

        button_rect = self.start_button_rect()
        pygame.draw.rect(self.screen, (221, 157, 43), button_rect, border_radius=9)
        button_text = self.font_ui.render("Start Game", True, (20, 22, 27))
        self.screen.blit(button_text, (button_rect.centerx - button_text.get_width() // 2, button_rect.y + 15))

        enter_hint = self.font_small.render("Press Enter or click Start Game", True, (180, 190, 205))
        self.screen.blit(enter_hint, (w // 2 - enter_hint.get_width() // 2, button_rect.bottom + 16))

        if self.seed_error:
            err = self.font_small.render(self.seed_error, True, (238, 116, 116))
            self.screen.blit(err, (w // 2 - err.get_width() // 2, input_rect.bottom + 10))

    def draw_play_mode(self):
        self.draw_terrain()
        self.draw_trees()

        scaled = pygame.transform.smoothscale(self.world_surface, self.screen.get_size())
        self.screen.blit(scaled, (0, 0))

        self.draw_crosshair()
        self.draw_inventory_hud()

        seed_display = self.font_small.render(f"Seed: {self.seed_text}", True, (236, 240, 246))
        self.screen.blit(seed_display, (14, 12))

        loot_display = self.font_small.render(f"Logs: {self.logs}  Saplings: {self.saplings}", True, (236, 240, 246))
        self.screen.blit(loot_display, (14, 34))

        punch_hint = self.font_small.render("Punch: Left Click or F", True, (236, 240, 246))
        self.screen.blit(punch_hint, (14, 56))

        if self.action_message_timer > 0.0:
            msg = self.font_small.render(self.action_message, True, (249, 227, 128))
            w, _ = self.screen.get_size()
            self.screen.blit(msg, (w // 2 - msg.get_width() // 2, 14))

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                elif self.mode == "start":
                    self.handle_start_event(event)
                elif self.mode == "play":
                    self.handle_play_event(event)

            if self.mode == "play":
                self.update_player(dt)

            if self.mode == "start":
                self.draw_start_screen()
            else:
                self.draw_play_mode()

            pygame.display.flip()

        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    Game().run()

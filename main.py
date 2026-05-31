import math
import os
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
VIEW_DISTANCE = 85
CAMERA_HEIGHT = 10.0
TURN_STEP_RADIANS = math.radians(1.0)
TURN_STEP_INTERVAL = 1.0 / 16.0
MOVE_SPEED = 22.0
JUMP_VELOCITY = 12.5
GRAVITY = 30.0
TREE_COUNT = 120
TREE_AREA_RADIUS = 220.0
MAX_STACK_SIZE = 32
MAX_HEALTH = 30
DAY_DURATION_SECONDS = 300.0
NIGHT_DURATION_SECONDS = 300.0

SKY_TOP = (110, 156, 209)
SKY_BOTTOM = (181, 214, 238)
NIGHT_SKY_TOP = (13, 22, 41)
NIGHT_SKY_BOTTOM = (35, 52, 86)


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
        self.game_time_seconds = 0.0

        self.world_surface = pygame.Surface((LOW_RES_WIDTH, LOW_RES_HEIGHT))
        self.day_sky_surface = self.build_sky_surface(SKY_TOP, SKY_BOTTOM)
        self.night_sky_surface = self.build_sky_surface(NIGHT_SKY_TOP, NIGHT_SKY_BOTTOM)

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
        self.player_ground_height = 0.0
        self.jump_offset = 0.0
        self.vertical_velocity = 0.0
        self.is_grounded = True
        self.turn_hold_a = 0.0
        self.turn_hold_d = 0.0
        self.max_health = MAX_HEALTH
        self.health = self.max_health

        self.active_slot = 0
        self.inventory_slots = [None] * 8
        self.armor_slots = [None] * 4
        self.item_sprites = self.load_item_sprites()
        self.full_heart_sprite, self.empty_heart_sprite = self.load_heart_sprites()
        self.tree_sprite = self.load_tree_sprite()
        self.tree_sprite_scale_cache = {}
        self.tree_hitboxes = []
        self.trees = []
        self.action_message = ""
        self.action_message_timer = 0.0
        self.crafting_open = False

        self.terrain = SeededTerrain(self.generate_seed())
        self.player_ground_height = self.terrain.height(self.player_x, self.player_z)
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
        self.player_ground_height = self.terrain.height(self.player_x, self.player_z)
        self.jump_offset = 0.0
        self.vertical_velocity = 0.0
        self.is_grounded = True
        self.turn_hold_a = 0.0
        self.turn_hold_d = 0.0
        self.health = self.max_health
        self.game_time_seconds = 0.0
        self.inventory_slots = [None] * 8
        self.action_message = ""
        self.action_message_timer = 0.0
        self.crafting_open = False

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
        if self.crafting_open and event.type == pygame.MOUSEBUTTONDOWN:
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                self.crafting_open = not self.crafting_open
                if self.crafting_open:
                    self.action_message = "Crafting open: Enter/C planks, V sticks, X wooden axe"
                else:
                    self.action_message = "Crafting closed"
                self.action_message_timer = 1.4
                return

            if self.crafting_open:
                if event.key == pygame.K_ESCAPE:
                    self.crafting_open = False
                    self.action_message = "Crafting closed"
                    self.action_message_timer = 1.0
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_c):
                    self.craft_planks()
                elif event.key == pygame.K_v:
                    self.craft_sticks()
                elif event.key == pygame.K_x:
                    self.craft_wooden_axe()
                return

            if pygame.K_1 <= event.key <= pygame.K_8:
                self.active_slot = event.key - pygame.K_1
            elif event.key == pygame.K_SPACE and self.is_grounded:
                self.vertical_velocity = JUMP_VELOCITY
                self.is_grounded = False
            elif event.key == pygame.K_f:
                self.punch_tree()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.punch_tree()
            elif event.button == 3:
                self.chop_tree_at_cursor(event.pos)

    def start_button_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(w // 2 - 170, h // 2 + 74, 340, 56)

    def update_player(self, dt: float):
        self.game_time_seconds += dt

        if self.crafting_open:
            if self.action_message_timer > 0.0:
                self.action_message_timer = max(0.0, self.action_message_timer - dt)
            return

        keys = pygame.key.get_pressed()

        if keys[pygame.K_a]:
            self.turn_hold_a += dt
            steps = int(self.turn_hold_a / TURN_STEP_INTERVAL)
            if steps > 0:
                self.player_yaw -= TURN_STEP_RADIANS * steps
                self.turn_hold_a -= TURN_STEP_INTERVAL * steps
        else:
            self.turn_hold_a = 0.0

        if keys[pygame.K_d]:
            self.turn_hold_d += dt
            steps = int(self.turn_hold_d / TURN_STEP_INTERVAL)
            if steps > 0:
                self.player_yaw += TURN_STEP_RADIANS * steps
                self.turn_hold_d -= TURN_STEP_INTERVAL * steps
        else:
            self.turn_hold_d = 0.0

        forward_x = math.sin(self.player_yaw)
        forward_z = math.cos(self.player_yaw)

        move = 0.0
        if keys[pygame.K_w]:
            move += 1.0
        if keys[pygame.K_s]:
            move -= 1.0

        self.player_x += forward_x * move * MOVE_SPEED * dt
        self.player_z += forward_z * move * MOVE_SPEED * dt
        self.player_ground_height = self.terrain.height(self.player_x, self.player_z)

        if not self.is_grounded:
            self.jump_offset += self.vertical_velocity * dt
            self.vertical_velocity -= GRAVITY * dt

            if self.jump_offset <= 0.0:
                self.jump_offset = 0.0
                self.vertical_velocity = 0.0
                self.is_grounded = True

        if self.action_message_timer > 0.0:
            self.action_message_timer = max(0.0, self.action_message_timer - dt)

    @staticmethod
    def create_wood_sprite(size: int) -> pygame.Surface:
        sprite = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(sprite, (102, 65, 41), (4, 8, size - 8, size - 14), border_radius=4)
        pygame.draw.rect(sprite, (134, 88, 58), (6, 10, size - 12, size - 18), border_radius=3)
        pygame.draw.line(sprite, (88, 52, 31), (8, size - 9), (size - 8, size - 9), 2)
        pygame.draw.line(sprite, (88, 52, 31), (8, 13), (size - 8, 13), 2)
        return sprite

    @staticmethod
    def create_axe_sprite(size: int) -> pygame.Surface:
        sprite = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(sprite, (125, 87, 60), (13, 7, 5, size - 10), border_radius=2)
        pygame.draw.polygon(sprite, (174, 182, 198), [(18, 8), (28, 6), (28, 17), (18, 18)])
        pygame.draw.polygon(sprite, (152, 160, 176), [(18, 12), (10, 8), (9, 18), (18, 20)])
        return sprite

    def load_item_sprites(self) -> dict[str, pygame.Surface]:
        sprite_size = 30
        sprites = {
            "wood": self.create_wood_sprite(sprite_size),
            "sapling": self.create_wood_sprite(sprite_size),
            "planks": self.create_wood_sprite(sprite_size),
            "sticks": self.create_wood_sprite(sprite_size),
            "wooden_axe": self.create_axe_sprite(sprite_size),
        }

        sapling_path = os.path.join("sprites", "sappling1.png")
        if os.path.exists(sapling_path):
            sapling = pygame.image.load(sapling_path).convert_alpha()
            sprites["sapling"] = pygame.transform.smoothscale(sapling, (sprite_size, sprite_size))

        planks_path = os.path.join("sprites", "planks1.png")
        if os.path.exists(planks_path):
            planks = pygame.image.load(planks_path).convert_alpha()
            sprites["planks"] = pygame.transform.smoothscale(planks, (sprite_size, sprite_size))

        stick_paths = [
            os.path.join("sprites", "stick1.png"),
            os.path.join("sprties", "stick1.png"),
        ]
        for stick_path in stick_paths:
            if os.path.exists(stick_path):
                stick = pygame.image.load(stick_path).convert_alpha()
                sprites["sticks"] = pygame.transform.smoothscale(stick, (sprite_size, sprite_size))
                break

        axe_paths = [
            os.path.join("sprites", "wooden axe1.png"),
            os.path.join("sprites", "wooden_axe1.png"),
            os.path.join("sprties", "wooden axe1.png"),
        ]
        for axe_path in axe_paths:
            if os.path.exists(axe_path):
                axe = pygame.image.load(axe_path).convert_alpha()
                sprites["wooden_axe"] = pygame.transform.smoothscale(axe, (sprite_size, sprite_size))
                break

        return sprites

    def load_tree_sprite(self) -> pygame.Surface:
        sprite = pygame.Surface((64, 96), pygame.SRCALPHA)
        pygame.draw.rect(sprite, (98, 63, 42), (28, 50, 8, 42), border_radius=2)
        pygame.draw.circle(sprite, (56, 131, 54), (32, 42), 24)
        pygame.draw.circle(sprite, (66, 150, 61), (24, 34), 14)
        pygame.draw.circle(sprite, (66, 150, 61), (40, 34), 14)

        tree_paths = [
            os.path.join("sprites", "tree1.png"),
            os.path.join("sprties", "tree1.png"),
        ]
        for tree_path in tree_paths:
            if os.path.exists(tree_path):
                sprite = pygame.image.load(tree_path).convert_alpha()
                break

        return sprite

    def load_heart_sprites(self) -> tuple[pygame.Surface, pygame.Surface]:
        size = 18
        full = pygame.Surface((size, size), pygame.SRCALPHA)
        empty = pygame.Surface((size, size), pygame.SRCALPHA)

        # Fallback procedural hearts in case files are missing.
        pygame.draw.circle(full, (225, 66, 79), (6, 6), 5)
        pygame.draw.circle(full, (225, 66, 79), (12, 6), 5)
        pygame.draw.polygon(full, (225, 66, 79), [(2, 8), (16, 8), (9, 17)])

        pygame.draw.circle(empty, (188, 191, 201), (6, 6), 5, 2)
        pygame.draw.circle(empty, (188, 191, 201), (12, 6), 5, 2)
        pygame.draw.polygon(empty, (188, 191, 201), [(2, 8), (16, 8), (9, 17)], 2)

        full_paths = [
            os.path.join("sprites", "full heart1.png"),
            os.path.join("sprties", "full heart1.png"),
        ]
        empty_paths = [
            os.path.join("sprites", "emtpy heart1.png"),
            os.path.join("sprites", "empty heart1.png"),
            os.path.join("sprties", "emtpy heart1.png"),
        ]

        for p in full_paths:
            if os.path.exists(p):
                loaded = pygame.image.load(p).convert_alpha()
                full = pygame.transform.smoothscale(loaded, (size, size))
                break

        for p in empty_paths:
            if os.path.exists(p):
                loaded = pygame.image.load(p).convert_alpha()
                empty = pygame.transform.smoothscale(loaded, (size, size))
                break

        return full, empty

    def set_health(self, health_value: int):
        self.health = max(0, min(self.max_health, health_value))

    def take_damage(self, amount: int):
        self.set_health(self.health - max(0, amount))

    def heal(self, amount: int):
        self.set_health(self.health + max(0, amount))

    def draw_health_hud(self):
        heart_size = self.full_heart_sprite.get_width()
        gap = 4
        hearts_per_row = 10
        rows = 3

        total_width = hearts_per_row * heart_size + (hearts_per_row - 1) * gap
        x_start = 14
        y_start = 84

        heart_index = 0
        for row in range(rows):
            for col in range(hearts_per_row):
                x = x_start + col * (heart_size + gap)
                y = y_start + row * (heart_size + gap)
                sprite = self.full_heart_sprite if heart_index < self.health else self.empty_heart_sprite
                self.screen.blit(sprite, (x, y))
                heart_index += 1

        hp_text = self.font_small.render(f"HP: {self.health}/{self.max_health}", True, (236, 240, 246))
        self.screen.blit(hp_text, (x_start + total_width + 12, y_start + heart_size))

    def get_scaled_tree_sprite(self, target_height: int) -> pygame.Surface:
        h = max(8, target_height)
        if h in self.tree_sprite_scale_cache:
            return self.tree_sprite_scale_cache[h]

        base_w, base_h = self.tree_sprite.get_size()
        scaled_w = max(4, int(base_w * (h / max(1, base_h))))
        scaled = pygame.transform.smoothscale(self.tree_sprite, (scaled_w, h))
        self.tree_sprite_scale_cache[h] = scaled
        return scaled

    def add_item_to_inventory(self, item_name: str, amount: int) -> int:
        remaining = amount
        item_stack_limit = self.max_stack_for_item(item_name)

        for slot in self.inventory_slots:
            if slot is None:
                continue
            if slot["item"] != item_name or slot["count"] >= item_stack_limit:
                continue

            can_add = min(item_stack_limit - slot["count"], remaining)
            slot["count"] += can_add
            remaining -= can_add
            if remaining == 0:
                return amount

        for i in range(len(self.inventory_slots)):
            if self.inventory_slots[i] is not None:
                continue

            can_add = min(item_stack_limit, remaining)
            self.inventory_slots[i] = {"item": item_name, "count": can_add}
            remaining -= can_add
            if remaining == 0:
                return amount

        return amount - remaining

    @staticmethod
    def max_stack_for_item(item_name: str) -> int:
        if item_name == "wooden_axe":
            return 1
        return MAX_STACK_SIZE

    def count_item(self, item_name: str) -> int:
        total = 0
        for slot in self.inventory_slots:
            if slot is not None and slot["item"] == item_name:
                total += slot["count"]
        return total

    def has_equipped_wooden_axe(self) -> bool:
        slot = self.inventory_slots[self.active_slot]
        return slot is not None and slot["item"] == "wooden_axe" and slot["count"] > 0

    def remove_item_from_inventory(self, item_name: str, amount: int) -> int:
        remaining = amount
        for i in range(len(self.inventory_slots) - 1, -1, -1):
            slot = self.inventory_slots[i]
            if slot is None or slot["item"] != item_name:
                continue

            take = min(slot["count"], remaining)
            slot["count"] -= take
            remaining -= take

            if slot["count"] == 0:
                self.inventory_slots[i] = None

            if remaining == 0:
                return amount

        return amount - remaining

    def craft_planks(self):
        if self.count_item("wood") < 1:
            self.action_message = "Need at least 1 log to craft planks"
            self.action_message_timer = 1.4
            return

        removed = self.remove_item_from_inventory("wood", 1)
        if removed < 1:
            self.action_message = "Craft failed"
            self.action_message_timer = 1.2
            return

        added = self.add_item_to_inventory("planks", 2)
        if added < 2:
            self.add_item_to_inventory("wood", 1)
            self.action_message = "No inventory space for planks"
            self.action_message_timer = 1.4
            return

        self.action_message = "Crafted 2 planks from 1 log"
        self.action_message_timer = 1.4

    def craft_sticks(self):
        if self.count_item("planks") < 1:
            self.action_message = "Need at least 1 plank to craft sticks"
            self.action_message_timer = 1.4
            return

        removed = self.remove_item_from_inventory("planks", 1)
        if removed < 1:
            self.action_message = "Craft failed"
            self.action_message_timer = 1.2
            return

        added = self.add_item_to_inventory("sticks", 5)
        if added < 5:
            self.add_item_to_inventory("planks", 1)
            self.action_message = "No inventory space for sticks"
            self.action_message_timer = 1.4
            return

        self.action_message = "Crafted 5 sticks from 1 plank"
        self.action_message_timer = 1.4

    def craft_wooden_axe(self):
        if self.count_item("planks") < 3 or self.count_item("sticks") < 2:
            self.action_message = "Need 3 planks and 2 sticks to craft a wooden axe"
            self.action_message_timer = 1.6
            return

        removed_planks = self.remove_item_from_inventory("planks", 3)
        removed_sticks = self.remove_item_from_inventory("sticks", 2)
        if removed_planks < 3 or removed_sticks < 2:
            if removed_planks > 0:
                self.add_item_to_inventory("planks", removed_planks)
            if removed_sticks > 0:
                self.add_item_to_inventory("sticks", removed_sticks)
            self.action_message = "Craft failed"
            self.action_message_timer = 1.2
            return

        added = self.add_item_to_inventory("wooden_axe", 1)
        if added < 1:
            self.add_item_to_inventory("planks", 3)
            self.add_item_to_inventory("sticks", 2)
            self.action_message = "No inventory space for wooden axe"
            self.action_message_timer = 1.4
            return

        self.action_message = "Crafted 1 wooden axe"
        self.action_message_timer = 1.4

    def camera_world_height(self) -> float:
        return self.player_ground_height + CAMERA_HEIGHT + self.jump_offset

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

        self.harvest_tree(best_tree)

    def harvest_tree(self, tree: dict):
        tree["alive"] = False
        bonus = 4 if self.has_equipped_wooden_axe() else 0
        logs = random.randint(1, 5) + bonus
        saplings = random.randint(1, 3) + bonus
        sticks = random.randint(2, 7) + bonus

        added_logs = self.add_item_to_inventory("wood", logs)
        added_saplings = self.add_item_to_inventory("sapling", saplings)
        added_sticks = self.add_item_to_inventory("sticks", sticks)
        dropped_logs = logs - added_logs
        dropped_saplings = saplings - added_saplings
        dropped_sticks = sticks - added_sticks

        self.action_message = f"Collected {added_logs} logs, {added_saplings} saplings, {added_sticks} sticks"
        if bonus > 0:
            self.action_message += " (+4 axe bonus)"
        if dropped_logs > 0 or dropped_saplings > 0 or dropped_sticks > 0:
            self.action_message += (
                f" ({dropped_logs} logs, {dropped_saplings} saplings, {dropped_sticks} sticks dropped)"
            )
        self.action_message_timer = 1.8

    def chop_tree_at_cursor(self, mouse_pos: tuple[int, int]):
        if not self.tree_hitboxes:
            self.action_message = "No tree under cursor"
            self.action_message_timer = 1.0
            return

        screen_w, screen_h = self.screen.get_size()
        low_x = int(mouse_pos[0] * LOW_RES_WIDTH / max(1, screen_w))
        low_y = int(mouse_pos[1] * LOW_RES_HEIGHT / max(1, screen_h))

        selected_tree = None
        selected_distance = 1e9
        for hit in reversed(self.tree_hitboxes):
            rect = hit["rect"]
            tree = hit["tree"]
            if not tree["alive"]:
                continue
            if rect.collidepoint(low_x, low_y):
                selected_tree = tree
                selected_distance = hit["distance"]
                break

        if selected_tree is None:
            self.action_message = "No tree under cursor"
            self.action_message_timer = 1.0
            return

        if selected_distance > 10.0:
            self.action_message = "Tree is too far away"
            self.action_message_timer = 1.0
            return

        self.harvest_tree(selected_tree)

    def is_daytime(self) -> bool:
        cycle = DAY_DURATION_SECONDS + NIGHT_DURATION_SECONDS
        t = self.game_time_seconds % cycle
        return t < DAY_DURATION_SECONDS

    def time_until_phase_change(self) -> float:
        cycle = DAY_DURATION_SECONDS + NIGHT_DURATION_SECONDS
        t = self.game_time_seconds % cycle
        if t < DAY_DURATION_SECONDS:
            return DAY_DURATION_SECONDS - t
        return cycle - t

    def build_sky_surface(self, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> pygame.Surface:
        surface = pygame.Surface((LOW_RES_WIDTH, LOW_RES_HEIGHT))
        for y in range(LOW_RES_HEIGHT):
            t = y / max(1, LOW_RES_HEIGHT - 1)
            color = (
                int(top_color[0] + (bottom_color[0] - top_color[0]) * t),
                int(top_color[1] + (bottom_color[1] - top_color[1]) * t),
                int(top_color[2] + (bottom_color[2] - top_color[2]) * t),
            )
            pygame.draw.line(surface, color, (0, y), (LOW_RES_WIDTH, y))
        return surface

    def draw_terrain(self):
        if self.is_daytime():
            self.world_surface.blit(self.day_sky_surface, (0, 0))
        else:
            self.world_surface.blit(self.night_sky_surface, (0, 0))
        current_camera_height = self.camera_world_height()

        for sx in range(LOW_RES_WIDTH):
            ray_angle = self.player_yaw + (sx / LOW_RES_WIDTH - 0.5) * FOV
            dx = math.sin(ray_angle)
            dz = math.cos(ray_angle)

            max_y = LOW_RES_HEIGHT - 1
            distance = 1.0
            while distance < VIEW_DISTANCE and max_y > 0:
                wx = self.player_x + dx * distance
                wz = self.player_z + dz * distance

                ground_h = self.terrain.height(wx, wz)
                projected = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
                projected = max(0, min(LOW_RES_HEIGHT - 1, projected))

                if projected < max_y:
                    color = self.terrain.ground_color(ground_h, distance)
                    pygame.draw.line(self.world_surface, color, (sx, projected), (sx, max_y))
                    max_y = projected

                distance += 1.1

    def draw_trees(self):
        current_camera_height = self.camera_world_height()
        self.tree_hitboxes = []
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
            trunk_bottom_y = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
            tree_top_h = ground_h + tree["trunk"] + tree["crown"]
            tree_top_y = HORIZON - int((tree_top_h - current_camera_height) * 85.0 / distance)

            sprite_h = max(8, trunk_bottom_y - tree_top_y)
            tree_sprite = self.get_scaled_tree_sprite(sprite_h)
            sprite_x = sx - tree_sprite.get_width() // 2
            sprite_y = trunk_bottom_y - tree_sprite.get_height()

            self.world_surface.blit(tree_sprite, (sprite_x, sprite_y))
            self.tree_hitboxes.append(
                {
                    "tree": tree,
                    "distance": distance,
                    "rect": pygame.Rect(sprite_x, sprite_y, tree_sprite.get_width(), tree_sprite.get_height()),
                }
            )

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

            hotkey = self.font_small.render(str(i + 1), True, (220, 224, 232))
            self.screen.blit(hotkey, (rect.x + 4, rect.y + 2))

            slot = self.inventory_slots[i]
            if slot is not None:
                sprite = self.item_sprites.get(slot["item"])
                if sprite is not None:
                    self.screen.blit(sprite, (rect.x + 11, rect.y + 11))

                count_text = self.font_small.render(str(slot["count"]), True, (250, 250, 250))
                self.screen.blit(
                    count_text,
                    (rect.right - count_text.get_width() - 4, rect.bottom - count_text.get_height() - 2),
                )

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

    def draw_crafting_overlay(self):
        w, h = self.screen.get_size()
        panel_w, panel_h = 410, 330
        panel_rect = pygame.Rect(w // 2 - panel_w // 2, h // 2 - panel_h // 2, panel_w, panel_h)

        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        self.screen.blit(dim, (0, 0))

        pygame.draw.rect(self.screen, (17, 24, 34), panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, (146, 160, 179), panel_rect, width=2, border_radius=10)

        title = self.font_ui.render("Crafting Grid (3x3)", True, (232, 236, 242))
        self.screen.blit(title, (panel_rect.x + 16, panel_rect.y + 14))

        slot_size = 64
        gap = 9
        grid_w = slot_size * 3 + gap * 2
        grid_x = panel_rect.centerx - grid_w // 2
        grid_y = panel_rect.y + 52

        for row in range(3):
            for col in range(3):
                r = pygame.Rect(grid_x + col * (slot_size + gap), grid_y + row * (slot_size + gap), slot_size, slot_size)
                pygame.draw.rect(self.screen, (30, 40, 54), r, border_radius=7)
                pygame.draw.rect(self.screen, (118, 131, 149), r, width=2, border_radius=7)

        recipe_text = self.font_small.render(
            "Recipes: 1 Log->2 Planks | 1 Plank->5 Sticks | 3 Planks+2 Sticks->Axe",
            True,
            (230, 234, 240),
        )
        self.screen.blit(recipe_text, (panel_rect.x + 16, panel_rect.y + 262))

        hint_text = self.font_small.render("Enter/C: planks, V: sticks, X: axe, R/Esc: close", True, (199, 209, 223))
        self.screen.blit(hint_text, (panel_rect.x + 16, panel_rect.y + 286))

        center_slot = pygame.Rect(grid_x + slot_size + gap, grid_y + slot_size + gap, slot_size, slot_size)
        if self.count_item("wood") > 0:
            wood_sprite = self.item_sprites.get("wood")
            if wood_sprite is not None:
                self.screen.blit(wood_sprite, (center_slot.x + 17, center_slot.y + 17))

        result_rect = pygame.Rect(panel_rect.right - 96, panel_rect.y + 146, 72, 72)
        pygame.draw.rect(self.screen, (35, 47, 61), result_rect, border_radius=7)
        pygame.draw.rect(self.screen, (138, 150, 167), result_rect, width=2, border_radius=7)
        planks_sprite = self.item_sprites.get("planks")
        if planks_sprite is not None:
            self.screen.blit(planks_sprite, (result_rect.x + 21, result_rect.y + 21))

        stick_result_rect = pygame.Rect(panel_rect.right - 186, panel_rect.y + 146, 72, 72)
        pygame.draw.rect(self.screen, (35, 47, 61), stick_result_rect, border_radius=7)
        pygame.draw.rect(self.screen, (138, 150, 167), stick_result_rect, width=2, border_radius=7)
        sticks_sprite = self.item_sprites.get("sticks")
        if sticks_sprite is not None:
            self.screen.blit(sticks_sprite, (stick_result_rect.x + 21, stick_result_rect.y + 21))

        axe_result_rect = pygame.Rect(panel_rect.right - 276, panel_rect.y + 146, 72, 72)
        pygame.draw.rect(self.screen, (35, 47, 61), axe_result_rect, border_radius=7)
        pygame.draw.rect(self.screen, (138, 150, 167), axe_result_rect, width=2, border_radius=7)
        axe_sprite = self.item_sprites.get("wooden_axe")
        if axe_sprite is not None:
            self.screen.blit(axe_sprite, (axe_result_rect.x + 21, axe_result_rect.y + 21))

        arrow_start = (center_slot.right + 8, center_slot.centery)
        arrow_end = (result_rect.x - 8, result_rect.centery)
        pygame.draw.line(self.screen, (211, 219, 228), arrow_start, arrow_end, 3)
        pygame.draw.polygon(
            self.screen,
            (211, 219, 228),
            [(arrow_end[0], arrow_end[1]), (arrow_end[0] - 10, arrow_end[1] - 6), (arrow_end[0] - 10, arrow_end[1] + 6)],
        )

    def draw_play_mode(self):
        self.draw_terrain()
        self.draw_trees()

        if not self.is_daytime():
            # Darken world during night while keeping HUD readable.
            dark_overlay = pygame.Surface((LOW_RES_WIDTH, LOW_RES_HEIGHT), pygame.SRCALPHA)
            dark_overlay.fill((0, 0, 18, 78))
            self.world_surface.blit(dark_overlay, (0, 0))

        scaled = pygame.transform.smoothscale(self.world_surface, self.screen.get_size())
        self.screen.blit(scaled, (0, 0))

        self.draw_crosshair()
        self.draw_inventory_hud()

        seed_display = self.font_small.render(f"Seed: {self.seed_text}", True, (236, 240, 246))
        self.screen.blit(seed_display, (14, 12))

        phase_name = "Day" if self.is_daytime() else "Night"
        secs = int(self.time_until_phase_change())
        mins = secs // 60
        rem = secs % 60
        phase_display = self.font_small.render(f"{phase_name} ({mins}:{rem:02d} to change)", True, (236, 240, 246))
        self.screen.blit(phase_display, (14, 154))

        total_logs = self.count_item("wood")
        total_saplings = self.count_item("sapling")
        total_planks = self.count_item("planks")
        total_sticks = self.count_item("sticks")
        total_axes = self.count_item("wooden_axe")
        loot_display = self.font_small.render(
            (
                f"Logs: {total_logs}  Saplings: {total_saplings}  Planks: {total_planks}  "
                f"Sticks: {total_sticks}  Axes: {total_axes}"
            ),
            True,
            (236, 240, 246),
        )
        self.screen.blit(loot_display, (14, 34))

        punch_hint = self.font_small.render("Punch: Left Click/F  Chop Cursor: Right Click  Craft: R", True, (236, 240, 246))
        self.screen.blit(punch_hint, (14, 56))

        self.draw_health_hud()

        if self.crafting_open:
            self.draw_crafting_overlay()

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

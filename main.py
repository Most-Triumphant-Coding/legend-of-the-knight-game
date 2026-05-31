import math
import os
import random
import sys

import pygame


WIDTH = 1280
HEIGHT = 720
FPS = 128

LOW_RES_WIDTH = 320
LOW_RES_HEIGHT = 180

FOV = math.radians(70)
HORIZON = LOW_RES_HEIGHT // 2 - 8
VIEW_DISTANCE = 85
CAMERA_HEIGHT = 10.0
TURN_STEP_RADIANS = math.radians(5.0)
MOVE_SPEED = 22.0
JUMP_VELOCITY = 12.5
GRAVITY = 30.0
TREE_COUNT = 120
TREE_AREA_RADIUS = 220.0
MAX_STACK_SIZE = 32
MAX_HEALTH = 30
DAY_DURATION_SECONDS = 60.0
NIGHT_DURATION_SECONDS = 60.0
TIER1_SKELETON_MAX_HEALTH = 10
TIER2_SKELETON_MAX_HEALTH = 10
TIER1_SKELETON_SPAWN_INTERVAL = 5.0
TIER2_SKELETON_SPAWN_INTERVAL = 10.0
TIER1_SKELETON_MAX_COUNT = 10
TIER2_SKELETON_MAX_COUNT = 6
IRON_HELMET_DAMAGE_REDUCTION = 0.35
SHEEP_SPAWN_INTERVAL = 1.0
SHEEP_MAX_COUNT = 28
SHEEP_MAX_HEALTH = 3

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
        self.start_notice = ""

        self.player_x = 0.0
        self.player_z = 0.0
        self.player_yaw = 0.0
        self.player_ground_height = 0.0
        self.jump_offset = 0.0
        self.vertical_velocity = 0.0
        self.is_grounded = True
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
        self.skeleton_sprites = self.load_skeleton_sprites()
        self.skeleton_sprite_scale_cache = {}
        self.skeleton_hitboxes = []
        self.skeletons = []
        self.sheep_sprite = self.load_sheep_sprite()
        self.sheep_sprite_scale_cache = {}
        self.sheep_hitboxes = []
        self.sheep = []
        self.sheep_spawn_timer = 0.0
        self.tier1_skeleton_spawn_timer = 0.0
        self.tier2_skeleton_spawn_timer = 0.0
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
        self.health = self.max_health
        self.game_time_seconds = 0.0
        self.inventory_slots = [None] * 8
        self.armor_slots = [None] * 4
        self.skeletons = []
        self.sheep = []
        self.sheep_spawn_timer = 0.0
        self.tier1_skeleton_spawn_timer = 0.0
        self.tier2_skeleton_spawn_timer = 0.0
        self.action_message = ""
        self.action_message_timer = 0.0
        self.crafting_open = False
        self.start_notice = ""

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
                    self.action_message = "Crafting open: Enter/C planks, V sticks, X wooden axe, B bed"
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
                elif event.key == pygame.K_b:
                    self.craft_bed()
                return

            if pygame.K_1 <= event.key <= pygame.K_8:
                self.active_slot = event.key - pygame.K_1
            elif event.key == pygame.K_SPACE and self.is_grounded:
                self.vertical_velocity = JUMP_VELOCITY
                self.is_grounded = False
            elif event.key == pygame.K_q:
                self.consume_meat_from_active_slot()
            elif event.key == pygame.K_f:
                if not self.player_attack_skeleton():
                    self.punch_tree()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if not self.player_attack_skeleton(event.pos):
                    self.punch_tree()
            elif event.button == 3:
                self.chop_tree_at_cursor(event.pos)

    def start_button_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(w // 2 - 170, h // 2 + 74, 340, 56)

    def update_player(self, dt: float):
        self.game_time_seconds += dt
        self.update_skeletons(dt)
        self.update_sheep(dt)

        if self.crafting_open:
            if self.action_message_timer > 0.0:
                self.action_message_timer = max(0.0, self.action_message_timer - dt)
            return

        keys = pygame.key.get_pressed()

        if keys[pygame.K_a]:
            self.player_yaw -= TURN_STEP_RADIANS

        if keys[pygame.K_d]:
            self.player_yaw += TURN_STEP_RADIANS

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
            "bone": self.create_wood_sprite(sprite_size),
            "iron_sword": self.create_axe_sprite(sprite_size),
            "iron_ingot": self.create_wood_sprite(sprite_size),
            "iron_helmet": self.create_axe_sprite(sprite_size),
            "meat": self.create_wood_sprite(sprite_size),
            "wool": self.create_wood_sprite(sprite_size),
            "bed": self.create_wood_sprite(sprite_size),
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

        sword_paths = [
            os.path.join("sprites", "iron sword2.png"),
            os.path.join("sprites", "iron_sword2.png"),
            os.path.join("sprties", "iron sword2.png"),
        ]
        for sword_path in sword_paths:
            if os.path.exists(sword_path):
                sword = pygame.image.load(sword_path).convert_alpha()
                sprites["iron_sword"] = pygame.transform.smoothscale(sword, (sprite_size, sprite_size))
                break

        bone_paths = [
            os.path.join("sprites", "bone1.png"),
            os.path.join("sprties", "bone1.png"),
        ]
        for bone_path in bone_paths:
            if os.path.exists(bone_path):
                bone = pygame.image.load(bone_path).convert_alpha()
                sprites["bone"] = pygame.transform.smoothscale(bone, (sprite_size, sprite_size))
                break

        ingot_paths = [
            os.path.join("sprites", "iron ingot1.png"),
            os.path.join("sprites", "iron_ingot1.png"),
            os.path.join("sprties", "iron ingot1.png"),
        ]
        for ingot_path in ingot_paths:
            if os.path.exists(ingot_path):
                ingot = pygame.image.load(ingot_path).convert_alpha()
                sprites["iron_ingot"] = pygame.transform.smoothscale(ingot, (sprite_size, sprite_size))
                break

        helmet_paths = [
            os.path.join("sprites", "iron helmet1.png"),
            os.path.join("sprites", "iron_helmet1.png"),
            os.path.join("sprites", "iron helment1.png"),
            os.path.join("sprties", "iron helmet1.png"),
        ]
        for helmet_path in helmet_paths:
            if os.path.exists(helmet_path):
                helmet = pygame.image.load(helmet_path).convert_alpha()
                sprites["iron_helmet"] = pygame.transform.smoothscale(helmet, (sprite_size, sprite_size))
                break

        meat_paths = [
            os.path.join("sprites", "meat1.png"),
            os.path.join("sprties", "meat1.png"),
        ]
        for meat_path in meat_paths:
            if os.path.exists(meat_path):
                meat = pygame.image.load(meat_path).convert_alpha()
                sprites["meat"] = pygame.transform.smoothscale(meat, (sprite_size, sprite_size))
                break

        wool_paths = [
            os.path.join("sprites", "wool1.png"),
            os.path.join("sprties", "wool1.png"),
        ]
        for wool_path in wool_paths:
            if os.path.exists(wool_path):
                wool = pygame.image.load(wool_path).convert_alpha()
                sprites["wool"] = pygame.transform.smoothscale(wool, (sprite_size, sprite_size))
                break

        bed_paths = [
            os.path.join("sprites", "bed1.png"),
            os.path.join("sprties", "bed1.png"),
        ]
        for bed_path in bed_paths:
            if os.path.exists(bed_path):
                bed = pygame.image.load(bed_path).convert_alpha()
                sprites["bed"] = pygame.transform.smoothscale(bed, (sprite_size, sprite_size))
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
        final_damage = max(0, amount)
        if self.has_iron_helmet_equipped():
            final_damage = max(1, math.ceil(final_damage * (1.0 - IRON_HELMET_DAMAGE_REDUCTION)))
        self.set_health(self.health - final_damage)
        if self.health <= 0:
            self.handle_player_death()

    def heal(self, amount: int):
        self.set_health(self.health + max(0, amount))

    def handle_player_death(self):
        self.mode = "start"
        self.start_notice = "You died. Press Start Game to respawn."
        self.crafting_open = False
        self.action_message = ""
        self.action_message_timer = 0.0
        self.skeletons = []
        self.skeleton_hitboxes = []
        self.sheep = []
        self.sheep_hitboxes = []
        self.health = self.max_health
        self.tier1_skeleton_spawn_timer = 0.0
        self.tier2_skeleton_spawn_timer = 0.0
        self.sheep_spawn_timer = 0.0

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
        if item_name in ("wooden_axe", "iron_sword", "iron_helmet", "bed"):
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

    def equipped_weapon_damage(self) -> int:
        slot = self.inventory_slots[self.active_slot]
        if slot is None:
            return 1
        if slot["item"] == "wooden_axe":
            return 4
        if slot["item"] == "iron_sword":
            return 7
        return 1

    def consume_meat_from_active_slot(self):
        slot = self.inventory_slots[self.active_slot]
        if slot is not None and slot.get("item") == "bed" and slot.get("count", 0) > 0:
            if self.is_daytime():
                self.action_message = "You can only sleep through the night"
                self.action_message_timer = 1.0
                return

            slot["count"] -= 1
            if slot["count"] <= 0:
                self.inventory_slots[self.active_slot] = None

            cycle = DAY_DURATION_SECONDS + NIGHT_DURATION_SECONDS
            t = self.game_time_seconds % cycle
            self.game_time_seconds += cycle - t

            self.skeletons = []
            self.skeleton_hitboxes = []
            self.tier1_skeleton_spawn_timer = 0.0
            self.tier2_skeleton_spawn_timer = 0.0

            self.action_message = "Skipped the night. Bed consumed"
            self.action_message_timer = 1.4
            return

        if slot is None or slot.get("item") != "meat" or slot.get("count", 0) <= 0:
            self.action_message = "Hold meat to eat or hold a bed to skip night"
            self.action_message_timer = 1.0
            return

        if self.health >= self.max_health:
            self.action_message = "Health is already full"
            self.action_message_timer = 1.0
            return

        slot["count"] -= 1
        if slot["count"] <= 0:
            self.inventory_slots[self.active_slot] = None

        self.heal(5)
        self.action_message = "Ate meat and restored 5 HP"
        self.action_message_timer = 1.1

    def has_iron_helmet_equipped(self) -> bool:
        for armor_slot in self.armor_slots:
            if armor_slot is not None and armor_slot.get("item") == "iron_helmet":
                return True
        return False

    def auto_equip_iron_helmet(self):
        if self.has_iron_helmet_equipped():
            return

        if self.armor_slots[0] is None and self.count_item("iron_helmet") > 0:
            removed = self.remove_item_from_inventory("iron_helmet", 1)
            if removed >= 1:
                self.armor_slots[0] = {"item": "iron_helmet", "count": 1}

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

    def craft_bed(self):
        if self.count_item("wool") < 2 or self.count_item("planks") < 2:
            self.action_message = "Need 2 wool and 2 planks to craft a bed"
            self.action_message_timer = 1.6
            return

        removed_wool = self.remove_item_from_inventory("wool", 2)
        removed_planks = self.remove_item_from_inventory("planks", 2)
        if removed_wool < 2 or removed_planks < 2:
            if removed_wool > 0:
                self.add_item_to_inventory("wool", removed_wool)
            if removed_planks > 0:
                self.add_item_to_inventory("planks", removed_planks)
            self.action_message = "Craft failed"
            self.action_message_timer = 1.2
            return

        added = self.add_item_to_inventory("bed", 1)
        if added < 1:
            self.add_item_to_inventory("wool", 2)
            self.add_item_to_inventory("planks", 2)
            self.action_message = "No inventory space for bed"
            self.action_message_timer = 1.4
            return

        self.action_message = "Crafted 1 bed"
        self.action_message_timer = 1.4

    def load_skeleton_sprites(self) -> dict[int, pygame.Surface]:
        tier1 = pygame.Surface((48, 72), pygame.SRCALPHA)
        pygame.draw.rect(tier1, (205, 210, 220), (17, 14, 14, 36), border_radius=3)
        pygame.draw.circle(tier1, (225, 228, 236), (24, 10), 9)
        pygame.draw.rect(tier1, (190, 194, 203), (12, 50, 8, 18), border_radius=2)
        pygame.draw.rect(tier1, (190, 194, 203), (28, 50, 8, 18), border_radius=2)

        tier2 = pygame.Surface((48, 72), pygame.SRCALPHA)
        pygame.draw.rect(tier2, (172, 182, 201), (16, 14, 16, 38), border_radius=3)
        pygame.draw.circle(tier2, (205, 216, 236), (24, 10), 9)
        pygame.draw.rect(tier2, (150, 163, 188), (11, 52, 8, 18), border_radius=2)
        pygame.draw.rect(tier2, (150, 163, 188), (29, 52, 8, 18), border_radius=2)

        tier1_paths = [
            os.path.join("sprites", "skeleton1.png"),
            os.path.join("sprties", "skeleton1.png"),
        ]
        for p in tier1_paths:
            if os.path.exists(p):
                tier1 = pygame.image.load(p).convert_alpha()
                break

        tier2_paths = [
            os.path.join("sprites", "skeleton2.png"),
            os.path.join("sprties", "skeleton2.png"),
        ]
        for p in tier2_paths:
            if os.path.exists(p):
                tier2 = pygame.image.load(p).convert_alpha()
                break

        return {1: tier1, 2: tier2}

    def get_scaled_skeleton_sprite(self, tier: int, target_height: int) -> pygame.Surface:
        h = max(8, target_height)
        key = (tier, h)
        if key in self.skeleton_sprite_scale_cache:
            return self.skeleton_sprite_scale_cache[key]

        base_sprite = self.skeleton_sprites.get(tier, self.skeleton_sprites[1])
        base_w, base_h = base_sprite.get_size()
        scaled_w = max(4, int(base_w * (h / max(1, base_h))))
        scaled = pygame.transform.smoothscale(base_sprite, (scaled_w, h))
        self.skeleton_sprite_scale_cache[key] = scaled
        return scaled

    def spawn_skeleton_near_player(self, tier: int):
        angle = random.uniform(0.0, math.tau)
        dist = random.uniform(20.0, 45.0)
        sx = self.player_x + math.sin(angle) * dist
        sz = self.player_z + math.cos(angle) * dist
        max_hp = TIER1_SKELETON_MAX_HEALTH if tier == 1 else TIER2_SKELETON_MAX_HEALTH
        self.skeletons.append({"x": sx, "z": sz, "hp": max_hp, "attack_cd": 0.0, "tier": tier})

    def kill_skeleton(self, skeleton: dict):
        if skeleton in self.skeletons:
            self.skeletons.remove(skeleton)

        tier = skeleton.get("tier", 1)
        bones = random.randint(1, 5)
        added_bones = self.add_item_to_inventory("bone", bones)
        dropped_bones = bones - added_bones

        dropped_parts = []
        self.action_message = f"Skeleton tier {tier} defeated: +{added_bones} bone"

        if tier == 1:
            got_sword = random.random() < 0.25
            added_sword = 0
            if got_sword:
                added_sword = self.add_item_to_inventory("iron_sword", 1)
            if got_sword:
                if added_sword > 0:
                    self.action_message += " and +1 iron sword"
                else:
                    dropped_parts.append("1 iron sword")
        else:
            ingots = random.randint(0, 4)
            added_ingots = self.add_item_to_inventory("iron_ingot", ingots)
            dropped_ingots = ingots - added_ingots
            self.action_message += f", +{added_ingots} iron ingot"
            if dropped_ingots > 0:
                dropped_parts.append(f"{dropped_ingots} iron ingot")

            got_helmet = random.random() < 0.10
            if got_helmet:
                added_helmet = self.add_item_to_inventory("iron_helmet", 1)
                if added_helmet > 0:
                    self.auto_equip_iron_helmet()
                    self.action_message += " and +1 iron helmet"
                else:
                    dropped_parts.append("1 iron helmet")

        if dropped_bones > 0:
            dropped_parts.append(f"{dropped_bones} bone")
        if dropped_parts:
            self.action_message += " (dropped: " + ", ".join(dropped_parts) + ")"
        self.action_message_timer = 1.8

    def update_skeletons(self, dt: float):
        if self.is_daytime():
            self.skeletons.clear()
            self.skeleton_hitboxes = []
            self.tier1_skeleton_spawn_timer = 0.0
            self.tier2_skeleton_spawn_timer = 0.0
            return

        self.tier1_skeleton_spawn_timer += dt
        self.tier2_skeleton_spawn_timer += dt

        while self.tier1_skeleton_spawn_timer >= TIER1_SKELETON_SPAWN_INTERVAL:
            self.spawn_skeleton_near_player(1)
            self.tier1_skeleton_spawn_timer -= TIER1_SKELETON_SPAWN_INTERVAL

        while self.tier2_skeleton_spawn_timer >= TIER2_SKELETON_SPAWN_INTERVAL:
            self.spawn_skeleton_near_player(2)
            self.tier2_skeleton_spawn_timer -= TIER2_SKELETON_SPAWN_INTERVAL

        for skeleton in self.skeletons:
            if skeleton["attack_cd"] > 0.0:
                skeleton["attack_cd"] = max(0.0, skeleton["attack_cd"] - dt)

            dx = self.player_x - skeleton["x"]
            dz = self.player_z - skeleton["z"]
            dist = math.hypot(dx, dz)

            if dist > 1.8:
                speed = 5.5
                skeleton["x"] += (dx / max(0.001, dist)) * speed * dt
                skeleton["z"] += (dz / max(0.001, dist)) * speed * dt
            else:
                if skeleton["attack_cd"] <= 0.0:
                    damage = 3 if skeleton.get("tier", 1) == 2 else 1
                    self.take_damage(damage)
                    if self.mode != "play":
                        return
                    skeleton["attack_cd"] = 1.0
                    self.action_message = f"Skeleton tier {skeleton.get('tier', 1)} hit you for {damage} damage"
                    self.action_message_timer = 1.0

    def load_sheep_sprite(self) -> pygame.Surface:
        sheep = pygame.Surface((56, 42), pygame.SRCALPHA)
        pygame.draw.ellipse(sheep, (232, 232, 232), (8, 9, 40, 24))
        pygame.draw.ellipse(sheep, (254, 254, 254), (16, 6, 24, 20))
        pygame.draw.rect(sheep, (87, 78, 69), (42, 16, 10, 10), border_radius=3)
        pygame.draw.rect(sheep, (87, 78, 69), (17, 29, 5, 11), border_radius=2)
        pygame.draw.rect(sheep, (87, 78, 69), (34, 29, 5, 11), border_radius=2)

        sheep_paths = [
            os.path.join("sprites", "sheep1.png"),
            os.path.join("sprties", "sheep1.png"),
        ]
        for sheep_path in sheep_paths:
            if os.path.exists(sheep_path):
                sheep = pygame.image.load(sheep_path).convert_alpha()
                break

        return sheep

    def get_scaled_sheep_sprite(self, target_height: int) -> pygame.Surface:
        h = max(8, target_height)
        if h in self.sheep_sprite_scale_cache:
            return self.sheep_sprite_scale_cache[h]

        base_w, base_h = self.sheep_sprite.get_size()
        scaled_w = max(4, int(base_w * (h / max(1, base_h))))
        scaled = pygame.transform.smoothscale(self.sheep_sprite, (scaled_w, h))
        self.sheep_sprite_scale_cache[h] = scaled
        return scaled

    def spawn_sheep_near_player(self):
        angle = random.uniform(0.0, math.tau)
        dist = random.uniform(16.0, 40.0)
        sx = self.player_x + math.sin(angle) * dist
        sz = self.player_z + math.cos(angle) * dist
        self.sheep.append(
            {
                "x": sx,
                "z": sz,
                "hp": SHEEP_MAX_HEALTH,
                "wander_angle": random.uniform(-math.pi, math.pi),
                "wander_timer": random.uniform(0.2, 1.1),
            }
        )

    def kill_sheep(self, sheep: dict):
        if sheep in self.sheep:
            self.sheep.remove(sheep)

        meats = random.randint(1, 3)
        wool = random.randint(1, 2)
        added_meat = self.add_item_to_inventory("meat", meats)
        added_wool = self.add_item_to_inventory("wool", wool)
        dropped_meat = meats - added_meat
        dropped_wool = wool - added_wool

        self.action_message = f"Sheep defeated: +{added_meat} meat, +{added_wool} wool"
        if dropped_meat > 0 or dropped_wool > 0:
            self.action_message += f" ({dropped_meat} meat, {dropped_wool} wool dropped)"
        self.action_message_timer = 1.6

    def update_sheep(self, dt: float):
        if self.is_daytime():
            self.sheep_spawn_timer += dt
            while self.sheep_spawn_timer >= SHEEP_SPAWN_INTERVAL:
                self.sheep_spawn_timer -= SHEEP_SPAWN_INTERVAL
                if len(self.sheep) < SHEEP_MAX_COUNT:
                    self.spawn_sheep_near_player()

        for sheep in self.sheep:
            sheep["wander_timer"] -= dt
            if sheep["wander_timer"] <= 0.0:
                sheep["wander_angle"] = random.uniform(-math.pi, math.pi)
                sheep["wander_timer"] = random.uniform(0.5, 1.7)

            dx = sheep["x"] - self.player_x
            dz = sheep["z"] - self.player_z
            dist = math.hypot(dx, dz)

            if dist < 8.0:
                run_angle = math.atan2(dx, dz)
                speed = 7.8
                sheep["x"] += math.sin(run_angle) * speed * dt
                sheep["z"] += math.cos(run_angle) * speed * dt
            else:
                speed = 2.2
                sheep["x"] += math.sin(sheep["wander_angle"]) * speed * dt
                sheep["z"] += math.cos(sheep["wander_angle"]) * speed * dt

    def draw_sheep(self):
        current_camera_height = self.camera_world_height()
        self.sheep_hitboxes = []
        visible_sheep = []

        for sheep in self.sheep:
            dx = sheep["x"] - self.player_x
            dz = sheep["z"] - self.player_z
            distance = math.hypot(dx, dz)

            if distance <= 1.0 or distance > VIEW_DISTANCE:
                continue

            angle = math.atan2(dx, dz)
            rel_angle = self.wrap_angle(angle - self.player_yaw)
            if abs(rel_angle) > FOV * 0.62:
                continue

            visible_sheep.append((distance, rel_angle, sheep))

        visible_sheep.sort(reverse=True, key=lambda item: item[0])

        for distance, rel_angle, sheep in visible_sheep:
            sx = int((rel_angle / FOV + 0.5) * LOW_RES_WIDTH)
            if sx < -10 or sx > LOW_RES_WIDTH + 10:
                continue

            ground_h = self.terrain.height(sheep["x"], sheep["z"])
            feet_y = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
            top_h = ground_h + 8.0
            top_y = HORIZON - int((top_h - current_camera_height) * 85.0 / distance)

            sprite_h = max(8, feet_y - top_y)
            sheep_sprite = self.get_scaled_sheep_sprite(sprite_h)
            sprite_x = sx - sheep_sprite.get_width() // 2
            sprite_y = feet_y - sheep_sprite.get_height()

            self.world_surface.blit(sheep_sprite, (sprite_x, sprite_y))
            self.sheep_hitboxes.append(
                {
                    "sheep": sheep,
                    "distance": distance,
                    "rect": pygame.Rect(sprite_x, sprite_y, sheep_sprite.get_width(), sheep_sprite.get_height()),
                }
            )

    def player_attack_skeleton(self, mouse_pos: tuple[int, int] | None = None) -> bool:
        target = None
        target_distance = 1e9
        target_kind = "skeleton"

        if mouse_pos is not None:
            screen_w, screen_h = self.screen.get_size()
            low_x = int(mouse_pos[0] * LOW_RES_WIDTH / max(1, screen_w))
            low_y = int(mouse_pos[1] * LOW_RES_HEIGHT / max(1, screen_h))

            for hit in reversed(self.sheep_hitboxes):
                if hit["rect"].collidepoint(low_x, low_y):
                    target = hit["sheep"]
                    target_distance = hit["distance"]
                    target_kind = "sheep"
                    break

            for hit in reversed(self.skeleton_hitboxes):
                if hit["rect"].collidepoint(low_x, low_y):
                    target = hit["skeleton"]
                    target_distance = hit["distance"]
                    target_kind = "skeleton"
                    break
        else:
            for skeleton in self.skeletons:
                dx = skeleton["x"] - self.player_x
                dz = skeleton["z"] - self.player_z
                dist = math.hypot(dx, dz)
                if dist > 11.0:
                    continue
                target_angle = math.atan2(dx, dz)
                rel_angle = self.wrap_angle(target_angle - self.player_yaw)
                if abs(rel_angle) > math.radians(18):
                    continue
                if dist < target_distance:
                    target = skeleton
                    target_distance = dist
                    target_kind = "skeleton"

            for sheep in self.sheep:
                dx = sheep["x"] - self.player_x
                dz = sheep["z"] - self.player_z
                dist = math.hypot(dx, dz)
                if dist > 11.0:
                    continue
                target_angle = math.atan2(dx, dz)
                rel_angle = self.wrap_angle(target_angle - self.player_yaw)
                if abs(rel_angle) > math.radians(18):
                    continue
                if dist < target_distance:
                    target = sheep
                    target_distance = dist
                    target_kind = "sheep"

        if target is None:
            return False

        if target_distance > 11.0:
            if target_kind == "skeleton":
                self.action_message = "Skeleton is too far away"
            else:
                self.action_message = "Sheep is too far away"
            self.action_message_timer = 1.0
            return True

        dmg = self.equipped_weapon_damage()
        target["hp"] -= dmg
        if target["hp"] <= 0:
            if target_kind == "skeleton":
                self.kill_skeleton(target)
            else:
                self.kill_sheep(target)
        else:
            if target_kind == "skeleton":
                self.action_message = f"Hit skeleton for {dmg} damage ({target['hp']} HP left)"
            else:
                self.action_message = f"Hit sheep for {dmg} damage ({target['hp']} HP left)"
            self.action_message_timer = 1.0

        return True

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

    def draw_skeletons(self):
        current_camera_height = self.camera_world_height()
        self.skeleton_hitboxes = []
        visible_skeletons = []

        for skeleton in self.skeletons:
            dx = skeleton["x"] - self.player_x
            dz = skeleton["z"] - self.player_z
            distance = math.hypot(dx, dz)

            if distance <= 1.0 or distance > VIEW_DISTANCE:
                continue

            angle = math.atan2(dx, dz)
            rel_angle = self.wrap_angle(angle - self.player_yaw)
            if abs(rel_angle) > FOV * 0.62:
                continue

            visible_skeletons.append((distance, rel_angle, skeleton))

        visible_skeletons.sort(reverse=True, key=lambda item: item[0])

        for distance, rel_angle, skeleton in visible_skeletons:
            sx = int((rel_angle / FOV + 0.5) * LOW_RES_WIDTH)
            if sx < -10 or sx > LOW_RES_WIDTH + 10:
                continue

            ground_h = self.terrain.height(skeleton["x"], skeleton["z"])
            feet_y = HORIZON - int((ground_h - current_camera_height) * 85.0 / distance)
            top_h = ground_h + (16.0 if skeleton.get("tier", 1) == 2 else 14.0)
            top_y = HORIZON - int((top_h - current_camera_height) * 85.0 / distance)

            sprite_h = max(8, feet_y - top_y)
            skeleton_sprite = self.get_scaled_skeleton_sprite(skeleton.get("tier", 1), sprite_h)
            sprite_x = sx - skeleton_sprite.get_width() // 2
            sprite_y = feet_y - skeleton_sprite.get_height()

            self.world_surface.blit(skeleton_sprite, (sprite_x, sprite_y))
            self.skeleton_hitboxes.append(
                {
                    "skeleton": skeleton,
                    "distance": distance,
                    "rect": pygame.Rect(sprite_x, sprite_y, skeleton_sprite.get_width(), skeleton_sprite.get_height()),
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

        if self.start_notice:
            notice = self.font_small.render(self.start_notice, True, (240, 194, 116))
            self.screen.blit(notice, (w // 2 - notice.get_width() // 2, button_rect.bottom + 40))

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
            "Recipes: 1 Log->2 Planks | 1 Plank->5 Sticks | 3 Planks+2 Sticks->Axe | 2 Wool+2 Planks->Bed",
            True,
            (230, 234, 240),
        )
        self.screen.blit(recipe_text, (panel_rect.x + 16, panel_rect.y + 262))

        hint_text = self.font_small.render("Enter/C: planks, V: sticks, X: axe, B: bed, R/Esc: close", True, (199, 209, 223))
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

        bed_result_rect = pygame.Rect(panel_rect.right - 366, panel_rect.y + 146, 72, 72)
        pygame.draw.rect(self.screen, (35, 47, 61), bed_result_rect, border_radius=7)
        pygame.draw.rect(self.screen, (138, 150, 167), bed_result_rect, width=2, border_radius=7)
        bed_sprite = self.item_sprites.get("bed")
        if bed_sprite is not None:
            self.screen.blit(bed_sprite, (bed_result_rect.x + 21, bed_result_rect.y + 21))

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
        self.draw_sheep()
        self.draw_skeletons()

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
        total_bones = self.count_item("bone")
        total_ingots = self.count_item("iron_ingot")
        total_swords = self.count_item("iron_sword")
        total_helmets = self.count_item("iron_helmet") + (1 if self.has_iron_helmet_equipped() else 0)
        total_meat = self.count_item("meat")
        total_wool = self.count_item("wool")
        total_beds = self.count_item("bed")
        loot_display = self.font_small.render(
            (
                f"Logs: {total_logs}  Saplings: {total_saplings}  Planks: {total_planks}  "
                f"Sticks: {total_sticks}  Axes: {total_axes}  Bones: {total_bones}  Ingots: {total_ingots}  "
                f"Iron Swords: {total_swords}  Helmets: {total_helmets}  Meat: {total_meat}  Wool: {total_wool}  Beds: {total_beds}"
            ),
            True,
            (236, 240, 246),
        )
        self.screen.blit(loot_display, (14, 34))

        punch_hint = self.font_small.render(
            "Punch: Left Click/F  Chop Cursor: Right Click  Craft: R  Use Bed/Eat Meat: Q",
            True,
            (236, 240, 246),
        )
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

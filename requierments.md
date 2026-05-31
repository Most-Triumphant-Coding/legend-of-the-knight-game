# 3D First-Person Game Requirements

## Overview
Create a 3D first-person game where the player can move and rotate using keyboard controls.

## Input Requirements
- `W`: Move player forward
- `S`: Move player backward
- `A`: Turn player left
- `D`: Turn player right

## Core Gameplay Requirement
- The game must run in first-person perspective and respond to the movement/turning controls in real time.

## Terrain Generation Requirement
- The game world must take place on pseudo-randomly generated terrain.
- Terrain generation must start from a 16-digit numeric seed.

## Start Screen Requirement
- The game must include a start screen.
- The start screen must display the game name: Legend of the Knight.
- The start screen must include a Start Game button.
- The start screen must include an optional input field where the player can enter a numeric seed if they prefer.

## Inventory Requirement
- The player must have an in-game inventory with 8 general-purpose item slots.
- The player must also have 4 dedicated armor slots.
- The player must be able to switch the active general inventory slot using number keys.
- Key 1 selects slot 1, key 2 selects slot 2, and so on through key 8 selecting slot 8.

## HUD Requirement
- The player must have a crosshair in the middle of their screen at all times during gameplay.

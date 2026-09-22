import re
from typing import Set, Tuple
from .base import Environment, EnvironmentState, ActionResult

class GridWorldEnvironment(Environment):
    name = "grid_world"
    description = "2D Grid World navigation with obstacles and hidden treasure"

    def __init__(self, task_description: str = ""):
        self.task_description = task_description
        self.width = 5
        self.height = 5
        self.start_pos = (1, 1)
        self.goal_pos = (5, 5)
        
        # Try parsing dimensions or positions if specified in description
        m_dim = re.search(r'(\d+)\s*[xX*×]\s*(\d+)', task_description)
        if m_dim:
            self.width = int(m_dim.group(1))
            self.height = int(m_dim.group(2))
            
        coords = re.findall(r'\((\d+)\s*,\s*(\d+)\)', task_description)
        if len(coords) >= 2:
            self.start_pos = (int(coords[0][0]), int(coords[0][1]))
            self.goal_pos = (int(coords[-1][0]), int(coords[-1][1]))
        elif len(coords) == 1:
            self.start_pos = (int(coords[0][0]), int(coords[0][1]))
            self.goal_pos = (self.width, self.height)
        else:
            self.start_pos = (1, 1)
            self.goal_pos = (self.width, self.height)

        # Obstacles that leave clear paths available
        self.obstacles: Set[Tuple[int, int]] = {
            (2, 2),
            (3, 4),
            (4, 2)
        }
        # Ensure start and goal are never obstacles
        self.obstacles.discard(self.start_pos)
        self.obstacles.discard(self.goal_pos)
        
        self.known_obstacles: Set[Tuple[int, int]] = set()
        self.x = self.start_pos[0]
        self.y = self.start_pos[1]
        self.step_count = 0
        self.score = 0.0
        self.found_treasure = False

    async def observe(self) -> EnvironmentState:
        distance = abs(self.x - self.goal_pos[0]) + abs(self.y - self.goal_pos[1])
        status = "Treasure Found!" if self.found_treasure else "Exploring"
        desc = (
            f"Grid: 5x5 grid from (1,1) bottom-left to (5,5) top-right. "
            f"Current position: ({self.x}, {self.y}). Target treasure: ({self.goal_pos[0]}, {self.goal_pos[1]}). "
            f"Manhattan distance to treasure: {distance}. Moves made: {self.step_count}. "
            f"Known obstacles: {sorted(list(self.known_obstacles)) if self.known_obstacles else 'None discovered yet'}. "
            f"Directions: 'Right' increases x (x+1, y), 'Left' decreases x (x-1, y), 'Up' increases y (x, y+1), 'Down' decreases y (x, y-1)."
        )
        return EnvironmentState(
            score=self.score,
            description=desc,
            is_terminal=self.found_treasure,
            metadata={
                "x": self.x,
                "y": self.y,
                "goal": self.goal_pos,
                "distance": distance,
                "moves": self.step_count,
                "known_obstacles": list(self.known_obstacles),
                "status": status
            }
        )

    async def act(self, action: dict | str) -> ActionResult:
        direction = None
        valid_directions = {"up", "down", "left", "right"}

        if isinstance(action, str):
            direction = action.strip().lower()
        elif isinstance(action, dict):
            # Check direct keys
            for k in ["direction", "action", "move", "tool", "command"]:
                v = action.get(k)
                if isinstance(v, str) and v.strip().lower() in valid_directions:
                    direction = v.strip().lower()
                    break
            # Check nested parameters
            if not direction and "parameters" in action and isinstance(action["parameters"], dict):
                params = action["parameters"]
                for k in ["direction", "action", "move", "dir", "to"]:
                    v = params.get(k)
                    if isinstance(v, str) and v.strip().lower() in valid_directions:
                        direction = v.strip().lower()
                        break
                if not direction:
                    for v in params.values():
                        if isinstance(v, str) and v.strip().lower() in valid_directions:
                            direction = v.strip().lower()
                            break

        if not direction or direction not in valid_directions:
            return ActionResult(
                success=False,
                error=f"Invalid direction: '{direction}'. Valid directions are: Up, Down, Left, Right. Example: {{'tool': 'move', 'parameters': {{'direction': 'Right'}}}}",
                reward=-1.0
            )

        self.step_count += 1
        curr_pos = (self.x, self.y)
        target_x, target_y = self.x, self.y

        if direction == "up":
            target_y += 1
        elif direction == "down":
            target_y -= 1
        elif direction == "right":
            target_x += 1
        elif direction == "left":
            target_x -= 1

        target_pos = (target_x, target_y)

        # 1. Check boundary
        if target_x < 1 or target_x > self.width or target_y < 1 or target_y > self.height:
            return ActionResult(
                success=False,
                output=f"Blocked - boundary reached. Cannot move outside ({self.width}x{self.height}) grid. Position remains ({self.x}, {self.y}).",
                reward=-2.0,
                metadata={"status": "boundary_blocked", "position": curr_pos}
            )

        # 2. Check obstacle
        if target_pos in self.obstacles:
            self.known_obstacles.add(target_pos)
            return ActionResult(
                success=False,
                output=f"Blocked - an obstacle is present at ({target_x}, {target_y}). Cannot enter cell. Position remains ({self.x}, {self.y}).",
                reward=-3.0,
                metadata={"status": "obstacle_blocked", "position": curr_pos, "obstacle": target_pos}
            )

        # 3. Valid move
        self.x, self.y = target_x, target_y
        new_pos = (self.x, self.y)

        # 4. Check goal
        if new_pos == self.goal_pos:
            self.found_treasure = True
            self.score += 100.0
            return ActionResult(
                success=True,
                output=f"Treasure Found - task completed! Reached ({self.x}, {self.y}) in {self.step_count} moves! Goal achieved!",
                reward=100.0,
                state_change=f"Moved from {curr_pos} to {new_pos} (GOAL REACHED)",
                metadata={"status": "treasure_found", "position": new_pos, "moves": self.step_count}
            )

        # Closer to goal gets positive reward, further gets small penalty
        prev_dist = abs(curr_pos[0] - self.goal_pos[0]) + abs(curr_pos[1] - self.goal_pos[1])
        curr_dist = abs(new_pos[0] - self.goal_pos[0]) + abs(new_pos[1] - self.goal_pos[1])
        move_reward = 2.0 if curr_dist < prev_dist else -1.0
        self.score += move_reward

        return ActionResult(
            success=True,
            output=f"Safe - move was valid. Moved from {curr_pos} to {new_pos}. Remaining distance: {curr_dist}.",
            reward=move_reward,
            state_change=f"Moved from {curr_pos} to {new_pos}",
            metadata={"status": "safe", "position": new_pos}
        )

    async def reset(self) -> EnvironmentState:
        self.x = self.start_pos[0]
        self.y = self.start_pos[1]
        self.step_count = 0
        self.score = 0.0
        self.found_treasure = False
        return await self.observe()

    async def is_finished(self) -> bool:
        return self.found_treasure

    def get_available_actions(self) -> list[dict]:
        return [
            {
                "name": "move",
                "description": "Move one step on the grid towards the treasure. Valid directions: 'Right' (x+1), 'Up' (y+1), 'Left' (x-1), 'Down' (y-1).",
                "parameters": {
                    "direction": "string (One of: 'Right', 'Up', 'Left', 'Down')"
                }
            }
        ]

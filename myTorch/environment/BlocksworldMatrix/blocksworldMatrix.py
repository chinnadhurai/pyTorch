#!/usr/bin/env python

import os
import math
import numpy as np
import myTorch
from myTorch.environment.BlocksworldMatrix import Agent, Order, Block

class BlocksWorld(object):
    def __init__(self, height=50, width=50, max_num_blocks=20, is_agent_present=False, is_colorless=False):
        self._height = height
        self._width = width
        self._is_agent_present = is_agent_present
        self._max_num_blocks = max_num_blocks
        self._is_colorless = is_colorless
        self._agent = None

    @property
    def order(self):
        return self._order

    @property
    def height_at_loc(self):
        return self._height_at_loc

    @property
    def agent(self):
        return self._agent

    def reset(self, blocks_info, object_ids=None, order_look_up=None, target_height_at_loc=None):

        self._height_at_loc = [0]*self._width
        self._block_lookup = {}
        self._blocks = []
        self._num_blocks = sum([len(tower_info) for tower_info in blocks_info])
        self._num_colors = self._num_blocks if not self._is_colorless else 1
        self._num_steps = 0

        # reset world
        self._one_hot_world = np.zeros((self._max_num_blocks, self._width, self._height))
        self._world = np.zeros((self._width, self._height))

        tower_locations = np.random.choice(list(range(self._width)), size=len(blocks_info), replace=False)
        for t_id, tower_info in enumerate(blocks_info):
            for block_id in tower_info:
                block_id = float(block_id) if object_ids is None else object_ids[block_id]
                block = Block(block_id=block_id, color=block_id)
                loc_x = tower_locations[t_id]
                assert(self._height_at_loc[loc_x] < self._height-1)
                block.set_loc((loc_x, self._height_at_loc[loc_x]))
                loc_x, loc_y = block.loc
                self._world[loc_x, loc_y] = block.id
                self._block_lookup[block.loc] = block
                self._height_at_loc[loc_x] += 1
                self._blocks.append(block)

        self._order = Order(self._block_lookup, self._height_at_loc, order_look_up)

        if target_height_at_loc is not None:
            self._target_height_at_loc = target_height_at_loc

        if self._is_agent_present:
            self._one_hot_world = np.zeros((self._max_num_blocks+1, self._width, self._height))
            agent_loc_x = np.random.choice(list(range(self._width)))
            assert(self._height_at_loc[agent_loc_x] < self._height)

            self._agent = Agent(agent_id=1.0 if object_ids is None else object_ids[0])
            self._agent.set_loc((agent_loc_x, self._height_at_loc[agent_loc_x]))
            loc_x, loc_y = self._agent.loc
            self._world[loc_x, loc_y] = self._agent.id
            self._height_at_loc[loc_x] += 1

        return self._world

    def as_numpy(self, one_hot=False):
        if not one_hot:
            return self._world
        else:
            for i, block in enumerate(self._blocks):
                self._one_hot_world[i, block.loc[0], block.loc[1]] = 1.0
            if self._is_agent_present:
                self._one_hot_world[-1, self._agent.loc[0], self._agent.loc[1]] = 1.0
            return self._one_hot_world

    def is_matching(self, target):
        x,y = self._agent.loc
        self._world[x, y] = 0
        is_match = np.array_equal(self._world, target.as_numpy())
        self._world[x, y] = self._agent.id
        return is_match

    def _has_game_ended(self):
        if self._num_colors > 1:
            return (self._order.num_blocks_in_position == self._num_blocks)
        else:
            for loc in range(self._width):
                effective_height = (self._height_at_loc[loc])
                target_height = self._target_height_at_loc[loc]
                if loc == self._agent.loc[0]:
                    effective_height -= 1
                if target_height != effective_height:
                    return False
            return True

    def update(self, action):
        (x, y) = self._agent.loc
        self._num_steps += 1
        default_reward = -0.01*self._num_steps

        if action == "left":
            if x == 0: return default_reward, False
            if self._height - self._height_at_loc[x-1] > 1:
                dest_loc = (x-1, self._height_at_loc[x-1])
                self._agent.move(dest_loc, self._world, self._block_lookup, self._height_at_loc)
                return default_reward, False
                    
        elif action == "right":
            if x == (self._width - 1): return default_reward, False
            if self._height - self._height_at_loc[x+1] > 1:
                dest_loc = (x+1, self._height_at_loc[x+1])
                self._agent.move(dest_loc, self._world, self._block_lookup, self._height_at_loc)
                return default_reward, False

        elif action == "pick":
            if self._agent.block is not None: return default_reward, False
            if y == 0: return default_reward, False
            if (x,y-1) in self._block_lookup:
                block = self._block_lookup[(x,y-1)]
                self._agent.pick_up_block(block, self._world, self._block_lookup)
            return default_reward, False

        elif action == "drop":
            if self._agent.block is None: return default_reward, False
            block = self._agent.block
            picked_x, picked_y = self._agent.picked_loc
            in_position_before_drop = block.in_position

            self._agent.drop_block(self._world, self._block_lookup)
            if y > 0:
                block.set_in_position_flag(self._order.order_look_up, self._block_lookup[(x,y-1)])
            else:
                block.set_in_position_flag(self._order.order_look_up)

            in_position_after_drop = block.in_position
            reward = default_reward
            if self._num_colors > 1:
                if in_position_before_drop == True and in_position_after_drop == False:
                    reward += -1
                    self._order.add_to_num_blocks_in_position(-1)
                elif in_position_before_drop == False and in_position_after_drop == True:
                    reward += 1
                    self._order.add_to_num_blocks_in_position(1)

            elif self._num_colors == 1:
                if picked_x == x:
                    reward += 0
                else:
                    if (self._height_at_loc[x] - 1) <= self._target_height_at_loc[x]:
                        reward += 1
                    if (self._target_height_at_loc[picked_x] - self._height_at_loc[picked_x] >= 1):
                        reward += -2

            done = self._has_game_ended()
            if done and self._num_colors == 1:
                reward = 10
            return reward, done

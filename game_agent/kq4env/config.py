"""KQ4-specific constants: global variable indices, inventory items, game metadata."""

# Game metadata
GAME_ID = "kq4sci"
MAX_SCORE = 230
RESOLUTION = (320, 200)

# Global variable indices
SCORE = 15
POSSIBLE_SCORE = 16
ROOM = 11
PREV_ROOM = 12
NIGHT = 100
INDOORS = 101
ACT = 109  # Quest stage
DEATH = 127
TROLL_CHASING = 126
HENCHMAN_CHASING = 175
OGRE_CHASING = 165
WHALE_ROOM = 132
SCRIPT_RUNNING = 189  # Cutscene / no input accepted
ROOM_CHANGE_LOCK = 204
DEBUG_MODE = 215
MINSTREL_ROOM = 118
UNICORN_STATE = 123
UNICORN_ROOM = 124
LOLOTTE_ALIVE = 169

# Time globals (real-time clock)
TIME_START = 156
TIME_END = 160

# Game hour/minute globals (for in-game time display)
GAME_HOUR = 156
GAME_MINUTES = 157

# All globals we want to poll each tick
POLL_GLOBALS = [
    SCORE,
    POSSIBLE_SCORE,
    ROOM,
    PREV_ROOM,
    NIGHT,
    INDOORS,
    ACT,
    DEATH,
    TROLL_CHASING,
    HENCHMAN_CHASING,
    OGRE_CHASING,
    SCRIPT_RUNNING,
    ROOM_CHANGE_LOCK,
    MINSTREL_ROOM,
    UNICORN_STATE,
    UNICORN_ROOM,
    LOLOTTE_ALIVE,
    GAME_HOUR,
    GAME_MINUTES,
]

# Quest stages (gAct values)
QUEST_CAPTURED = 0
QUEST_FETCH_UNICORN = 1
QUEST_FETCH_HEN = 2
QUEST_FETCH_PANDORA = 3
QUEST_MARRIAGE_ENDGAME = 99

# Chase rooms
TROLL_CAVE_ROOMS = range(71, 77)  # 71-76
CASTLE_ROOMS = range(81, 94)  # 81-93

# Inventory items — names matching SCI object names for `send ?Name owner` queries
INVENTORY_ITEMS = [
    "Silver_Flute",
    "Diamond_Pouch",
    "Talisman",
    "Lantern__unlit_",
    "Pandora_s_Box",
    "Gold_Ball",
    "Witches__Glass_Eye",
    "Obsidian_Scarab",
    "Peacock_Feather",
    "Lute",
    "Small_Crown",
    "Frog",
    "Silver_Baby_Rattle",
    "Gold_Coins",
    "Cupid_s_Bow",
    "Shovel",
    "Axe",
    "Fishing_Pole",
    "Shakespeare_Book",
    "Worm",
    "Skeleton_Key",
    "Golden_Bridle",
    "Board",
    "Bone",
    "Dead_Fish",
    "Magic_Fruit",
    "Sheet_Music",
    "Silver_Whistle",
    "Locket",
    "Medal",
    "Toy_Horse",
    "Glass_Bottle",
    "Gold_Key",
    "Magic_Hen",
    "Rose",
    "Note",
]

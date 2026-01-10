"""Biathlon domain constants."""

# Discipline codes
RELAY_DISCIPLINE = "RL"
SINGLE_MIXED_RELAY_DISCIPLINE = "SR"
INDIVIDUAL_DISCIPLINES = {"SP", "PU", "IN", "MS"}

# Relay category codes
RELAY_WOMEN_CAT = "SW"
RELAY_MEN_CAT = "SM"
RELAY_MIXED_CAT = "MX"

# Shots per discipline (5 shots per stage)
# Sprint: 2 stages, others: 4 stages
SHOTS_PER_DISCIPLINE = {"SP": 10, "PU": 20, "IN": 20, "MS": 20}

# Skiing laps per discipline
SKI_LAPS = {"SP": 3, "PU": 5, "IN": 5, "MS": 5}

# Shooting stages (range visits) per discipline
SHOOTING_STAGES = {"SP": 2, "PU": 4, "IN": 4, "MS": 4}

# Gender/category mappings
GENDER_TO_CAT = {"women": "SW", "men": "SM"}
CAT_TO_GENDER = {"SW": "women", "SM": "men"}

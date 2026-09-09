"""Deterministic, privacy-preserving pseudonyms for student usernames.

Course-scoped reviewers (per-course passwords) must not see real student
identities, but still need to tell one student's conversations apart. This maps
each username to a stable, alliterative ``"Adjective Animal"`` pair — both words
share a first letter, e.g. ``"Brave Bear"`` — chosen from a SHA-256 of the
username. The same username always yields the same pair; the pair is one-way and
reveals nothing about the original identity.

Master-password (all-access) sessions and open local-dev bypass this and see the
real username; see ``database_ui/auth.py`` (``is_all_access``).
"""

from __future__ import annotations

import hashlib

# Adjectives and animals grouped by shared first letter, so a pair drawn from
# the same letter is alliterative. Only letters that have BOTH an adjective and
# an animal list are usable (see ``_LETTERS``); letters with no plausible animal
# (u, x, y, z) are simply omitted.
_ADJECTIVES: dict[str, tuple[str, ...]] = {
    "a": ("Able", "Agile", "Amber", "Amiable", "Ample", "Artful", "Astute", "Airy"),
    "b": ("Bold", "Brave", "Breezy", "Bright", "Brisk", "Bubbly", "Beaming", "Bouncy"),
    "c": ("Calm", "Cheery", "Chipper", "Clever", "Cozy", "Crafty", "Cuddly", "Curious"),
    "d": ("Dainty", "Dandy", "Dapper", "Daring", "Dashing", "Deft", "Dreamy", "Dutiful"),
    "e": ("Eager", "Earnest", "Easy", "Elated", "Epic", "Even", "Extra", "Eminent"),
    "f": ("Fabled", "Fancy", "Fearless", "Feisty", "Fluffy", "Friendly", "Frisky", "Funky"),
    "g": ("Gallant", "Gentle", "Giddy", "Glad", "Gleaming", "Goofy", "Grand", "Groovy"),
    "h": ("Handy", "Happy", "Hardy", "Hearty", "Helpful", "Hopeful", "Humble", "Honest"),
    "i": ("Icy", "Ideal", "Impish", "Inky", "Intent", "Iron", "Ivory", "Iconic"),
    "j": ("Jaunty", "Jazzy", "Jolly", "Jovial", "Joyful", "Jumpy", "Just", "Jubilant"),
    "k": ("Keen", "Kind", "Kindly", "Kingly", "Knowing", "Kooky", "Knightly", "Key"),
    "l": ("Lanky", "Limber", "Lively", "Lofty", "Loyal", "Lucky", "Lush", "Luminous"),
    "m": ("Mellow", "Merry", "Mighty", "Mild", "Mindful", "Modest", "Mystic", "Mirthful"),
    "n": ("Neat", "Nice", "Nifty", "Nimble", "Noble", "Nippy", "Novel", "Nomadic"),
    "o": ("Open", "Orderly", "Ornate", "Outgoing", "Optimal", "Opal", "Onward", "Original"),
    "p": ("Peppy", "Perky", "Placid", "Playful", "Plucky", "Polite", "Proud", "Prompt"),
    "q": ("Quaint", "Quick", "Quiet", "Quirky", "Quizzical", "Quotable", "Quality", "Quirked"),
    "r": ("Radiant", "Rapid", "Ready", "Regal", "Robust", "Rosy", "Ruddy", "Rustic"),
    "s": ("Sassy", "Serene", "Sharp", "Shiny", "Silly", "Sleepy", "Snappy", "Spry", "Sunny", "Swift"),
    "t": ("Tidy", "Timely", "Tiny", "Trusty", "Tranquil", "Tender", "Tough", "Tactful"),
    "v": ("Valiant", "Vast", "Velvet", "Vibrant", "Vivid", "Vocal", "Verdant", "Vaulting"),
    "w": ("Warm", "Whimsical", "Wily", "Winsome", "Wise", "Witty", "Wondrous", "Wiggly"),
}

_ANIMALS: dict[str, tuple[str, ...]] = {
    "a": ("Antelope", "Alpaca", "Armadillo", "Anteater", "Albatross", "Aardvark", "Axolotl", "Auk"),
    "b": ("Bear", "Badger", "Beaver", "Bison", "Bobcat", "Buffalo", "Butterfly", "Boar"),
    "c": ("Cat", "Cheetah", "Chipmunk", "Cobra", "Cougar", "Crane", "Coyote", "Crab"),
    "d": ("Deer", "Dolphin", "Dingo", "Donkey", "Dove", "Duck", "Dormouse", "Dragonfly"),
    "e": ("Eagle", "Elk", "Elephant", "Emu", "Egret", "Eel", "Ermine", "Earwig"),
    "f": ("Fox", "Falcon", "Ferret", "Finch", "Flamingo", "Frog", "Fawn", "Firefly"),
    "g": ("Goose", "Gazelle", "Gecko", "Gibbon", "Goat", "Gopher", "Grouse", "Guppy"),
    "h": ("Hawk", "Hare", "Hedgehog", "Heron", "Hamster", "Hyena", "Horse", "Hummingbird"),
    "i": ("Iguana", "Ibis", "Impala", "Inchworm", "Indri", "Isopod"),
    "j": ("Jaguar", "Jackal", "Jay", "Jellyfish", "Junco", "Jackrabbit"),
    "k": ("Koala", "Kangaroo", "Kestrel", "Kingfisher", "Kiwi", "Krill", "Kudu", "Kite"),
    "l": ("Lion", "Lemur", "Leopard", "Llama", "Lizard", "Lynx", "Lark", "Lobster"),
    "m": ("Moose", "Mole", "Meerkat", "Mongoose", "Manatee", "Mouse", "Magpie", "Marmot"),
    "n": ("Newt", "Nightingale", "Narwhal", "Nuthatch", "Numbat", "Nightjar"),
    "o": ("Otter", "Owl", "Ocelot", "Octopus", "Opossum", "Oriole", "Ox", "Osprey"),
    "p": ("Panda", "Panther", "Puffin", "Parrot", "Penguin", "Pony", "Possum", "Pelican"),
    "q": ("Quail", "Quokka", "Quetzal", "Quoll"),
    "r": ("Rabbit", "Raccoon", "Raven", "Robin", "Ram", "Reindeer", "Rooster", "Rhino"),
    "s": ("Snake", "Seal", "Sparrow", "Squirrel", "Swan", "Stork", "Skunk", "Salamander", "Swallow", "Snail"),
    "t": ("Tiger", "Toad", "Turtle", "Tapir", "Toucan", "Termite", "Trout", "Tortoise"),
    "v": ("Viper", "Vulture", "Vole", "Vervet", "Vicuna", "Viperfish"),
    "w": ("Wolf", "Walrus", "Weasel", "Wombat", "Woodpecker", "Wren", "Wallaby", "Warbler"),
}

# Letters usable for an alliterative pair: those with both lists populated.
_LETTERS: tuple[str, ...] = tuple(sorted(set(_ADJECTIVES) & set(_ANIMALS)))


def pseudonym(username: str) -> str:
    """A stable, alliterative ``"Adjective Animal"`` pseudonym for *username*.

    Deterministic: the same username always maps to the same pair. Different
    usernames almost always differ (collisions are possible and harmless — the
    pair carries no identity). Both words share a first letter.
    """
    digest = hashlib.sha256(username.encode("utf-8")).digest()
    letter = _LETTERS[int.from_bytes(digest[0:4], "big") % len(_LETTERS)]
    adjs = _ADJECTIVES[letter]
    animals = _ANIMALS[letter]
    adj = adjs[int.from_bytes(digest[4:8], "big") % len(adjs)]
    animal = animals[int.from_bytes(digest[8:12], "big") % len(animals)]
    return f"{adj} {animal}"


def display_identity(username: str | None, *, all_access: bool) -> str | None:
    """The identity string to expose for a conversation, per the login's scope.

    - No username (``None`` / empty) -> ``None`` (the caller renders "Anonymous").
    - All-access (master password or open local-dev) -> the real username.
    - Course-scoped -> the stable alliterative pseudonym.
    """
    if not username:
        return None
    if all_access:
        return username
    return pseudonym(username)

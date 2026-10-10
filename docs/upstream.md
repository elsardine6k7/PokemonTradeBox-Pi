# Upstream notes

The local build adds missing Pokémon friendship / happiness support to the PKHeX-backed builder.

It forwards Showdown Happiness/Friendship, accepts values 0–255, writes `PKM.CurrentFriendship`, exposes friendship from `Describe()`, and verifies it in `Unmet()`.

The change was tested with Sword / Shield using a Riolu built at friendship 255; after trading to retail Sword and leveling under the normal evolution condition, it evolved successfully.

Upstream pull request: https://github.com/Decryptu/pokeldn/pull/14

# Upstream notes

PokemonTradeBox-Pi v0.2.0 supports both the maintained friendship implementation in current pokeldn and the older v0.20.0 compatibility patch shipped in this repository.

Friendship / Happiness support was merged upstream in [Decryptu/pokeldn#14](https://github.com/Decryptu/pokeldn/pull/14). The maintained implementation writes the original trainer's friendship and accounts for the way receiving games rewrite handler friendship.

The local v0.20.0 compatibility patch is retained only for older installations. It was originally tested with Sword / Shield using a Riolu built at friendship 255; after trading to retail Sword and leveling under the normal evolution condition, it evolved successfully.

For new installs, prefer current upstream pokeldn.

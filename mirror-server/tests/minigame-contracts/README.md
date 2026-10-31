# Minigame relay contracts

This dependency-free .NET 8 executable compiles the actual authored
`NebulaMinigameState` (Board, Darts, Pool and Bowling TCP opcodes) and checks
the exact wire payloads it produces for synthetic seats: lobby/seat replies,
actor acknowledgements, rival/spectator relays, Chess/Draughts/TicTacToe
result reporting and disconnect cleanup.

Run from the repository root:

```sh
dotnet run --project mirror-server/tests/minigame-contracts
```

To keep compiler output outside the checkout, pass
`-p:BaseIntermediateOutputPath=<private>/obj/ -p:BaseOutputPath=<private>/bin/`
to `dotnet build` and run the produced `MinigameContracts.dll`.

The payloads follow the client receivers recorded in
`docs/research/minigame-contracts.md`. These checks do not run Unity, open a
listener, start the game or prove native multiplayer.

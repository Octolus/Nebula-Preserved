# World relay contracts

This dependency-free .NET 8 executable compiles the actual authored
`NebulaWorldState` and checks the exact wire payloads it produces for
`UpdateAnimationLayer` (opcode 93: relay, validation, late-joiner replay and
disconnect cleanup), together with the boat (31) snapshot and legacy generic
(94) delivery it shares a snapshot path with.
It also checks `NebulaLocomotionEchoes`, the ordering rule that tells the
client's automatic empty `15#guid#` frames (from `UpdateLocomotion` →
`RemoveLocomotion`) apart from deliberate removals: wheel switch, wheel
"none", bare removals, viewer-origin empties, login and the jetpack flight.

Run from the repository root:

```sh
dotnet run --project mirror-server/tests/world-contracts
```

To keep compiler output outside the checkout, pass
`-p:BaseIntermediateOutputPath=<private>/obj/ -p:BaseOutputPath=<private>/bin/`
to `dotnet build` and run the produced `WorldContracts.dll`.

The host-side delivery gates (loaded-avatar gate for 93, none for 94) live in
`NebulaInstanceServer.DeliverWorld` and are not exercised here. These checks do
not run Unity, open a listener, start the game or prove native multiplayer.

# Social publication contracts

This dependency-free .NET 8 executable compiles the actual authored
`NebulaSocialState` and relationship planner. It tests delayed, missing and
successful friendship persistence, exact overlay-expiry boundaries,
cross-instance notices, durable blocking and private-consent invalidation.
Its injected clock keeps the checks fast without sleeping.

Run from the repository root, supplying an existing temporary parent:

```sh
dotnet run --project mirror-server/tests/social-contracts -- /path/to/private/tmp
```

The source has no NuGet package dependency; the adjacent configuration disables
remote package feeds. Test files are created in unique subdirectories of the
supplied temporary parent and deleted after each case. To keep all compiler/cache
output outside the checkout, set `DOTNET_CLI_HOME`, `NUGET_PACKAGES`, `TEMP`/`TMP`
and MSBuild's `BaseIntermediateOutputPath`/`BaseOutputPath` to private locations.

The Unity JSON substitute is test-only and outside `Assets`. These checks do
not run Unity, open a listener, start a game or prove native multiplayer.
The fifteen-second publication grace is explicit preservation policy; HTTP is
the durable relationship authority. An uncommitted friendship event must never
grant private chat indefinitely.

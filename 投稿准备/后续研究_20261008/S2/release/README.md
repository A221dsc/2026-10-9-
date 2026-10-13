# S2 reviewed executable snapshots

These are byte-identical copies of artifacts/engineering/build_v7/s2_driver_native.exe and s2_driver_resource.exe. They are versioned with the S2 source freeze tag. The formal launcher keeps the original build_v7 paths because full capacity process receipts bind those actual executed paths.

The binaries include the unchanged production R6, matched LIST, matched Event16 and TLX. Native and resource modes are separate. Runtime, compiler, dependency and machine paths are recorded in the experiment lock; a new machine requires an explicit reproducibility run rather than substituting an old binary silently.

Engineering and formal evidence remain distinct. The tracked snapshots do not themselves authorize formal execution.

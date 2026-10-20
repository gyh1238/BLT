package types

// DefaultIndex is the default global index.
const DefaultIndex uint64 = 1

// DefaultGenesis returns the default genesis state per spec §4.5.
func DefaultGenesis() *GenesisState {
	return &GenesisState{
		Params:           DefaultParams(),
		InitialDelegates: BltDelegateSet{Delegates: []BltDelegate{}},
	}
}

// Validate performs basic genesis state validation.
func (gs GenesisState) Validate() error {
	if err := gs.Params.Validate(); err != nil {
		return err
	}
	// initial_delegates may be empty at chain bootstrap; once non-empty it
	// must match cluster_count and have no duplicate cluster_id values.
	if n := len(gs.InitialDelegates.Delegates); n > 0 {
		if uint32(n) != gs.Params.ClusterCount {
			return errInitialDelegatesLen(uint32(n), gs.Params.ClusterCount)
		}
		seen := make(map[uint32]struct{}, n)
		for _, d := range gs.InitialDelegates.Delegates {
			if _, dup := seen[d.ClusterId]; dup {
				return errDuplicateClusterID(d.ClusterId)
			}
			seen[d.ClusterId] = struct{}{}
		}
	}
	return nil
}

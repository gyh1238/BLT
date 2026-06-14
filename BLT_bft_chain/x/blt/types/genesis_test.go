package types_test

import (
	"testing"

	"leochain/x/blt/types"

	"github.com/stretchr/testify/require"
)

func TestGenesisState_Validate(t *testing.T) {
	tests := []struct {
		desc     string
		genState *types.GenesisState
		valid    bool
	}{
		{
			desc:     "default is valid",
			genState: types.DefaultGenesis(),
			valid:    true,
		},
		{
			desc: "explicit valid params",
			genState: &types.GenesisState{
				Params:           types.NewParams(12, 3500, 16384),
				InitialDelegates: types.BltDelegateSet{},
			},
			valid: true,
		},
		{
			desc: "zero cluster_count rejected",
			genState: &types.GenesisState{
				Params: types.NewParams(0, 3500, 16384),
			},
			valid: false,
		},
		{
			desc: "initial_delegates length must match cluster_count when non-empty",
			genState: &types.GenesisState{
				Params: types.NewParams(2, 3500, 16384),
				InitialDelegates: types.BltDelegateSet{
					Delegates: []types.BltDelegate{
						{ClusterId: 0, HeadId: 100, ValidatorAddress: "cosmosvaloper1xxx"},
					},
				},
			},
			valid: false,
		},
		{
			desc: "duplicate cluster_id rejected",
			genState: &types.GenesisState{
				Params: types.NewParams(2, 3500, 16384),
				InitialDelegates: types.BltDelegateSet{
					Delegates: []types.BltDelegate{
						{ClusterId: 0, HeadId: 100, ValidatorAddress: "cosmosvaloper1a"},
						{ClusterId: 0, HeadId: 101, ValidatorAddress: "cosmosvaloper1b"},
					},
				},
			},
			valid: false,
		},
	}
	for _, tc := range tests {
		t.Run(tc.desc, func(t *testing.T) {
			err := tc.genState.Validate()
			if tc.valid {
				require.NoError(t, err)
			} else {
				require.Error(t, err)
			}
		})
	}
}

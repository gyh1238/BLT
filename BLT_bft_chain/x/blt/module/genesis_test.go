package blt_test

import (
	"testing"

	keepertest "leochain/testutil/keeper"
	"leochain/testutil/nullify"
	blt "leochain/x/blt/module"
	"leochain/x/blt/types"

	"github.com/stretchr/testify/require"
)

func TestGenesis(t *testing.T) {
	genesisState := types.GenesisState{
		Params: types.DefaultParams(),

		// this line is used by starport scaffolding # genesis/test/state
	}

	k, ctx := keepertest.BltKeeper(t)
	blt.InitGenesis(ctx, k, genesisState)
	got := blt.ExportGenesis(ctx, k)
	require.NotNil(t, got)

	nullify.Fill(&genesisState)
	nullify.Fill(got)

	// this line is used by starport scaffolding # genesis/test/assert
}

package keeper_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	keepertest "leochain/testutil/keeper"
	"leochain/x/blt/types"
)

func TestGetParams(t *testing.T) {
	k, ctx := keepertest.BltKeeper(t)
	params := types.DefaultParams()

	require.NoError(t, k.SetParams(ctx, params))
	require.EqualValues(t, params, k.GetParams(ctx))
}

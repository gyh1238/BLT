package keeper_test

import (
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	keepertest "leochain/testutil/keeper"
	"leochain/x/blt/types"
)

// A chain whose genesis bound its delegates to real validators must never
// synthesize an epoch. Waiting for an external commit instead is a deadlock:
// the generator advances the stored reference every block, so a proposer
// sampling the current block time is always behind and is rejected as
// non-monotonic -- it can never produce the commit the guard waits for.
func TestGenerateEpoch_StandsDownWhenGenesisBindsValidators(t *testing.T) {
	k, _, ctx := setup(t)
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{
			{ClusterId: 0, HeadId: 100, ValidatorAddress: "cosmosvaloper1abc"},
			{ClusterId: 1, HeadId: 101, ValidatorAddress: "cosmosvaloper1def"},
		},
	}))

	for i := 0; i < 5; i++ {
		next := ctx.WithBlockHeight(keepertest.TestBlockHeight + int64(i)).
			WithBlockTime(keepertest.TestBlockTime.Add(time.Duration(i) * time.Second))
		require.NoError(t, k.GenerateEpoch(next))
	}
	_, ok := k.GetLatestEpoch(ctx)
	require.False(t, ok, "a validator-bound chain must not synthesize epochs")
}

// The digital-twin demo, where buildDelegateSet leaves the addresses empty,
// keeps generating.
func TestGenerateEpoch_RunsWhenDelegatesAreUnbound(t *testing.T) {
	k, _, ctx := setup(t)
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{
			{ClusterId: 0, HeadId: 100, ValidatorAddress: ""},
			{ClusterId: 1, HeadId: 101, ValidatorAddress: ""},
		},
	}))
	require.NoError(t, k.GenerateEpoch(ctx))
	snap, ok := k.GetLatestEpoch(ctx)
	require.True(t, ok)
	require.True(t, strings.HasPrefix(snap.Proposer, "SAT-"))
}

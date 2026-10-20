package keeper_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	sdk "github.com/cosmos/cosmos-sdk/types"

	keepertest "leochain/testutil/keeper"
	"leochain/x/blt/keeper"
	"leochain/x/blt/types"
)

// commitRounds commits `rounds` consecutive epochs, one per block, and returns
// the height of the first and last. This is the state a node that was
// disconnected has to catch up on.
func commitRounds(t *testing.T, rounds int) (k keeper.Keeper, ctx sdk.Context, first, last int64) {
	t.Helper()
	kk, ms, c, proposer := delegateSetup(t)
	for i := 0; i < rounds; i++ {
		at := keepertest.TestBlockTime.Add(time.Duration(i) * 3500 * time.Millisecond)
		rctx := c.WithBlockHeight(keepertest.TestBlockHeight + int64(i)).WithBlockTime(at)
		_, err := ms.CommitSyncBlock(rctx, &types.MsgCommitSyncBlock{
			Proposer: proposer,
			Body:     bodyAt([]uint32{100}, 1, at),
			EpochId:  uint32(i + 1),
		})
		require.NoError(t, err, "round %d", i)
	}
	return kk, c, keepertest.TestBlockHeight, keepertest.TestBlockHeight + int64(rounds) - 1
}

// The gRPC query must return the same epochs the keeper iterator walks, because
// a rejoining node reaches the history over the wire and not in-process. The
// height index is the one it has to use: epoch_id is a u8 and wraps every 256
// rounds, so a longer gap cannot be enumerated by id.
func TestEpochHistoryRangeQuery_WalksTheGap(t *testing.T) {
	k, ctx, first, last := commitRounds(t, 4)

	res, err := k.EpochHistoryRange(ctx, &types.QueryEpochHistoryRangeRequest{
		FromHeight: first, ToHeight: last,
	})
	require.NoError(t, err)
	require.Len(t, res.Snapshots, 4)
	require.False(t, res.Truncated)

	for i := 1; i < len(res.Snapshots); i++ {
		require.Greater(t, res.Snapshots[i].Height, res.Snapshots[i-1].Height,
			"the reply must be height-ordered, or a replay applies epochs out of order")
		require.Greater(t, res.Snapshots[i].Body.Global.GlobalRefTimeQ01Ns,
			res.Snapshots[i-1].Body.Global.GlobalRefTimeQ01Ns,
			"reference time must be monotone across the replayed gap")
	}
}

// A node that missed only the tail asks for only the tail.
func TestEpochHistoryRangeQuery_PartialWindow(t *testing.T) {
	k, ctx, first, last := commitRounds(t, 4)

	res, err := k.EpochHistoryRange(ctx, &types.QueryEpochHistoryRangeRequest{
		FromHeight: first + 2, ToHeight: last,
	})
	require.NoError(t, err)
	require.Len(t, res.Snapshots, 2)
	require.Equal(t, first+2, res.Snapshots[0].Height)
}

// Truncation has to be visible. A short answer that does not say it is short
// would let a node conclude it had replayed the whole gap when it had not,
// which is worse than an error: it would accept the head as verified.
func TestEpochHistoryRangeQuery_TruncationIsReported(t *testing.T) {
	k, ctx, first, last := commitRounds(t, 4)

	res, err := k.EpochHistoryRange(ctx, &types.QueryEpochHistoryRangeRequest{
		FromHeight: first, ToHeight: last, Limit: 2,
	})
	require.NoError(t, err)
	require.Len(t, res.Snapshots, 2)
	require.True(t, res.Truncated, "a capped window must be flagged, not silently shortened")

	// Continuing from the last height received completes the gap.
	next, err := k.EpochHistoryRange(ctx, &types.QueryEpochHistoryRangeRequest{
		FromHeight: res.Snapshots[len(res.Snapshots)-1].Height + 1,
		ToHeight:   last, Limit: 2,
	})
	require.NoError(t, err)
	require.Len(t, next.Snapshots, 2)
	require.False(t, next.Truncated)
}

// An empty window is not an error: a node that missed nothing asks and is told
// nothing happened. Distinguishing that from a failed query matters, because
// only one of the two means "you are up to date".
func TestEpochHistoryRangeQuery_EmptyWindowIsNotAnError(t *testing.T) {
	k, ctx, _, last := commitRounds(t, 2)

	res, err := k.EpochHistoryRange(ctx, &types.QueryEpochHistoryRangeRequest{
		FromHeight: last + 500, ToHeight: last + 600,
	})
	require.NoError(t, err)
	require.Empty(t, res.Snapshots)
	require.False(t, res.Truncated)
}

func TestEpochHistoryRangeQuery_RejectsBadWindow(t *testing.T) {
	k, ctx, first, last := commitRounds(t, 2)

	for name, req := range map[string]*types.QueryEpochHistoryRangeRequest{
		"reversed":      {FromHeight: last, ToHeight: first - 1},
		"negative from": {FromHeight: -1, ToHeight: last},
		"negative to":   {FromHeight: first, ToHeight: -5},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := k.EpochHistoryRange(ctx, req)
			require.Error(t, err)
			require.Equal(t, codes.InvalidArgument, status.Code(err))
		})
	}

	_, err := k.EpochHistoryRange(ctx, nil)
	require.Error(t, err)
}

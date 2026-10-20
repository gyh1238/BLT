package keeper_test

import (
	"testing"
	"time"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	keepertest "leochain/testutil/keeper"
	"leochain/testutil/sample"
	"leochain/x/blt/keeper"
	"leochain/x/blt/types"
)

// bodyAt is sampleBody with an explicit constellation reference instant, for
// the tests that need consecutive (or deliberately rolled-back) rounds.
func bodyAt(headIDs []uint32, members int, ts time.Time) types.BltBlockBody {
	b := sampleBody(headIDs, members)
	b.Global.GlobalRefTimeQ01Ns = refTimeAt(ts)
	return b
}

func sampleBody(headIDs []uint32, members int) types.BltBlockBody {
	cluster := make([]types.BltClusterSummary, len(headIDs))
	for i, h := range headIDs {
		cluster[i] = types.BltClusterSummary{ClusterId: uint32(i), HeadId: h}
	}
	mem := make([]types.BltMemberRecord, members)
	for i := range mem {
		mem[i] = types.BltMemberRecord{NodeId: uint32(i + 1), ClusterId: 0}
	}
	return types.BltBlockBody{
		Global: types.BltBodyGlobal{
			GlobalRefTimeQ01Ns: refTimeAt(keepertest.TestBlockTime),
			ClusterCount:       uint32(len(headIDs)),
			MemberCount:        uint32(members),
		},
		ClusterTable: cluster,
		MemberTable:  mem,
	}
}

// refTimeAt encodes a wall-clock instant the way a proposer must: 0.1 ns units
// measured from the module's anchor epoch.
func refTimeAt(ts time.Time) uint64 {
	return uint64((ts.UnixNano() - keeper.RefEpochUnixNano) * 10)
}

func setup(t testing.TB) (keeper.Keeper, types.MsgServer, sdk.Context) {
	k, ctx := keepertest.BltKeeper(t)
	return k, keeper.NewMsgServerImpl(k), ctx
}

func TestCommitSyncBlock_HappyPath(t *testing.T) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer}},
	}))

	body := sampleBody([]uint32{100}, 3)
	resp, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     body,
		EpochId:  7,
	})
	require.NoError(t, err)
	require.Equal(t, body.Global.GlobalRefTimeQ01Ns, resp.GlobalRefTimeQ01Ns)

	snap, ok := k.GetLatestEpoch(ctx)
	require.True(t, ok)
	require.Equal(t, uint32(7), snap.EpochId)
	require.Equal(t, proposer, snap.Proposer)

	hist, ok := k.GetEpochHistory(ctx, 7)
	require.True(t, ok)
	require.Equal(t, uint32(7), hist.EpochId)
}

func TestCommitSyncBlock_ProposerNotDelegate(t *testing.T) {
	_, ms, ctx := setup(t)
	body := sampleBody([]uint32{100}, 1)
	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: sample.AccAddress(),
		Body:     body,
	})
	require.ErrorIs(t, err, types.ErrProposerNotDelegate)
}

func TestCommitSyncBlock_UnknownHeadID(t *testing.T) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer}},
	}))
	body := sampleBody([]uint32{999}, 1)
	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     body,
	})
	require.ErrorIs(t, err, types.ErrUnknownClusterHead)
}

func TestCommitSyncBlock_PlausibilityOutOfTolerance(t *testing.T) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer}},
	}))
	body := sampleBody([]uint32{100}, 1)
	// Push head offset to 20 ms (PlausibilityToleranceQ01ns = 10 ms in q01ns).
	body.ClusterTable[0].HeadOffsetToGlobalQ01Ns = 200_000_000
	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     body,
	})
	require.ErrorIs(t, err, types.ErrPlausibility)
}

func TestQuery_LatestEpoch_NotFound(t *testing.T) {
	k, _, ctx := setup(t)
	_, err := k.LatestEpoch(ctx, &types.QueryLatestEpochRequest{})
	require.Error(t, err)
}

func TestQuery_DelegateSet_Empty(t *testing.T) {
	k, _, ctx := setup(t)
	resp, err := k.DelegateSet(ctx, &types.QueryDelegateSetRequest{})
	require.NoError(t, err)
	require.Empty(t, resp.DelegateSet.Delegates)
}

// TestCommitSyncBlock_OperatorAddressDelegate mirrors the shape that
// scripts/init_n_validators.sh actually produces: genesis initial_delegates
// carry the gentx operator address (cosmosvaloper1...), while the tx is signed
// by the account address (cosmos1...) of the same key. The other tests put the
// account address straight into the delegate set and so never exercise this.
func TestCommitSyncBlock_OperatorAddressDelegate(t *testing.T) {
	k, ms, ctx := setup(t)
	acc, err := sdk.AccAddressFromBech32(sample.AccAddress())
	require.NoError(t, err)
	operator := sdk.ValAddress(acc).String()
	require.NotEqual(t, acc.String(), operator)

	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: operator}},
	}))

	_, err = ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: acc.String(),
		Body:     sampleBody([]uint32{100}, 1),
		EpochId:  3,
	})
	require.NoError(t, err)

	snap, ok := k.GetLatestEpoch(ctx)
	require.True(t, ok)
	require.Equal(t, uint32(3), snap.EpochId)
}

// A signer that is not the delegate must still be rejected once operator
// addresses are accepted.
func TestCommitSyncBlock_OperatorAddressDelegate_WrongSigner(t *testing.T) {
	k, ms, ctx := setup(t)
	acc, err := sdk.AccAddressFromBech32(sample.AccAddress())
	require.NoError(t, err)
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: sdk.ValAddress(acc).String()}},
	}))

	_, err = ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: sample.AccAddress(),
		Body:     sampleBody([]uint32{100}, 1),
	})
	require.ErrorIs(t, err, types.ErrProposerNotDelegate)
}


// ----------------------------------------------------------------------------
// Ledger-dependent admission rules (plausibility.go)
//
// These are the cases a single authenticated snapshot cannot decide: each one
// is a well-formed, correctly signed message from an authorised delegate that
// the chain rejects only because it contradicts state the network already
// agreed on.
// ----------------------------------------------------------------------------

// delegateSetup registers one delegate (head 100) and returns its address.
func delegateSetup(t testing.TB) (keeper.Keeper, types.MsgServer, sdk.Context, string) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer}},
	}))
	return k, ms, ctx, proposer
}

// A head that asserts a global time an hour away from consensus block time is
// refused. The intra-message plausibility check cannot catch this: the cluster
// offsets it is compared against are supplied by the same proposer.
func TestCommitSyncBlock_RejectsFabricatedRefTime(t *testing.T) {
	_, ms, ctx, proposer := delegateSetup(t)

	for _, off := range []time.Duration{time.Hour, -time.Hour} {
		_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
			Proposer: proposer,
			Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime.Add(off)),
			EpochId:  1,
		})
		require.ErrorIs(t, err, types.ErrRefTimeSkew, "offset %s should be rejected", off)
	}
}

// Drift inside the tolerance window stays acceptable; the anchor bounds gross
// fabrication, it does not impose the sync algorithm's own accuracy target.
func TestCommitSyncBlock_AcceptsRefTimeWithinTolerance(t *testing.T) {
	_, ms, ctx, proposer := delegateSetup(t)

	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime.Add(-time.Second)),
		EpochId:  1,
	})
	require.NoError(t, err)
}

// Replaying a previously accepted global time to drag the swarm backwards is
// refused because the last accepted value is consensus state.
func TestCommitSyncBlock_RejectsRollback(t *testing.T) {
	_, ms, ctx, proposer := delegateSetup(t)

	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime),
		EpochId:  1,
	})
	require.NoError(t, err)

	next := ctx.WithBlockHeight(ctx.BlockHeight() + 1).
		WithBlockTime(keepertest.TestBlockTime.Add(3500 * time.Millisecond))
	_, err = ms.CommitSyncBlock(next, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		// Well inside the block-time tolerance, but behind the accepted epoch.
		Body:    bodyAt([]uint32{100}, 1, keepertest.TestBlockTime.Add(-time.Second)),
		EpochId: 2,
	})
	require.ErrorIs(t, err, types.ErrNonMonotonicTime)
}

// Re-using an epoch id that is already committed is refused, even at a new
// height with a later reference time: the id index would otherwise overwrite
// the snapshot the earlier round committed under that id.
func TestCommitSyncBlock_RejectsEpochIdReuse(t *testing.T) {
	k, ms, ctx, proposer := delegateSetup(t)

	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime),
		EpochId:  7,
	})
	require.NoError(t, err)
	first, ok := k.GetEpochHistory(ctx, 7)
	require.True(t, ok)

	next := ctx.WithBlockHeight(ctx.BlockHeight() + 1).
		WithBlockTime(keepertest.TestBlockTime.Add(3500 * time.Millisecond))
	_, err = ms.CommitSyncBlock(next, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime.Add(3500*time.Millisecond)),
		EpochId:  7,
	})
	require.ErrorIs(t, err, types.ErrEpochIdNotAdvancing)

	after, ok := k.GetEpochHistory(next, 7)
	require.True(t, ok)
	require.Equal(t, first.Height, after.Height, "the committed record for id 7 must not be replaced")
}

// Ids may skip ahead and wrap past 255; only reuse and backward ids are refused.
func TestCommitSyncBlock_AcceptsEpochIdGapAndWrap(t *testing.T) {
	_, ms, ctx, proposer := delegateSetup(t)
	ids := []uint32{250, 253, 2}
	for i, id := range ids {
		c := ctx.WithBlockHeight(ctx.BlockHeight() + int64(i)).
			WithBlockTime(keepertest.TestBlockTime.Add(time.Duration(i) * 3500 * time.Millisecond))
		_, err := ms.CommitSyncBlock(c, &types.MsgCommitSyncBlock{
			Proposer: proposer,
			Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime.Add(time.Duration(i)*3500*time.Millisecond)),
			EpochId:  id,
		})
		require.NoError(t, err, "epoch id %d", id)
	}
}

// A second commit at the same height is refused: one sync epoch per block, and
// a captured tx cannot be re-submitted into a round that is already closed.
func TestCommitSyncBlock_RejectsStaleRound(t *testing.T) {
	_, ms, ctx, proposer := delegateSetup(t)
	msg := &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100}, 1, keepertest.TestBlockTime),
		EpochId:  1,
	}
	_, err := ms.CommitSyncBlock(ctx, msg)
	require.NoError(t, err)

	_, err = ms.CommitSyncBlock(ctx, msg)
	require.ErrorIs(t, err, types.ErrStaleRound)
}

// Consecutive honest rounds are accepted and land in the height index in
// order, which is what a rejoining node scans to replay the gap it missed.
func TestCommitSyncBlock_HeightIndexedHistoryIsOrdered(t *testing.T) {
	k, ms, ctx, proposer := delegateSetup(t)

	const rounds = 4
	for i := 0; i < rounds; i++ {
		at := keepertest.TestBlockTime.Add(time.Duration(i) * 3500 * time.Millisecond)
		rctx := ctx.WithBlockHeight(keepertest.TestBlockHeight + int64(i)).WithBlockTime(at)
		_, err := ms.CommitSyncBlock(rctx, &types.MsgCommitSyncBlock{
			Proposer: proposer,
			Body:     bodyAt([]uint32{100}, 1, at),
			EpochId:  uint32(i + 1),
		})
		require.NoError(t, err, "round %d", i)
	}

	var heights []int64
	var refs []uint64
	k.IterateEpochHistoryByHeight(ctx, 0, keepertest.TestBlockHeight+rounds, func(s types.BltEpochSnapshot) bool {
		heights = append(heights, s.Height)
		refs = append(refs, s.Body.Global.GlobalRefTimeQ01Ns)
		return true
	})
	require.Len(t, heights, rounds)
	for i := 1; i < rounds; i++ {
		require.Greater(t, heights[i], heights[i-1], "history must be height-ordered")
		require.Greater(t, refs[i], refs[i-1], "reference time must be monotone across the replayed gap")
	}

	// A partial replay, the way a node that missed only the last two rounds
	// would request it.
	var partial int
	k.IterateEpochHistoryByHeight(ctx, keepertest.TestBlockHeight+2, keepertest.TestBlockHeight+rounds,
		func(types.BltEpochSnapshot) bool { partial++; return true })
	require.Equal(t, 2, partial)
}

// A body that names the same head twice. Each head_id is individually known, so
// the per-row lookup passes and the count check passes; what is wrong is the
// shape of the set. A proposer doing this doubles one cluster's weight in the
// median the plausibility test is computed over, so it must be rejected on the
// duplicate rather than on either of the checks that happen to look right.
func TestCommitSyncBlock_RejectsDuplicateHead(t *testing.T) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{
			{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer},
			{ClusterId: 1, HeadId: 101, ValidatorAddress: proposer},
		},
	}))

	body := bodyAt([]uint32{100, 100}, 2, keepertest.TestBlockTime)
	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer, Body: body, EpochId: 1,
	})
	require.ErrorIs(t, err, types.ErrDuplicateClusterHead)
}

// The honest shape with the same two heads is accepted, so the rejection above
// is about the duplication and not about the cluster table generally.
func TestCommitSyncBlock_AcceptsDistinctHeads(t *testing.T) {
	k, ms, ctx := setup(t)
	proposer := sample.AccAddress()
	require.NoError(t, k.SetDelegateSet(ctx, types.BltDelegateSet{
		Delegates: []types.BltDelegate{
			{ClusterId: 0, HeadId: 100, ValidatorAddress: proposer},
			{ClusterId: 1, HeadId: 101, ValidatorAddress: proposer},
		},
	}))
	_, err := ms.CommitSyncBlock(ctx, &types.MsgCommitSyncBlock{
		Proposer: proposer,
		Body:     bodyAt([]uint32{100, 101}, 2, keepertest.TestBlockTime),
		EpochId:  1,
	})
	require.NoError(t, err)
}

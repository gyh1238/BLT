package keeper_test

import (
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	keepertest "leochain/testutil/keeper"
	"leochain/testutil/sample"
	"leochain/x/blt/keeper"
	"leochain/x/blt/types"
)

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
			GlobalRefTimeQ01Ns: 1_000_000,
			ClusterCount:       uint32(len(headIDs)),
			MemberCount:        uint32(members),
		},
		ClusterTable: cluster,
		MemberTable:  mem,
	}
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

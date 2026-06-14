package keeper

import (
	"context"
	"fmt"
	"sort"
	"strconv"

	errorsmod "cosmossdk.io/errors"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"leochain/x/blt/types"
)

// PlausibilityToleranceQ01ns bounds the spread allowed between the asserted
// global ref time and the median of the per-cluster-head offsets to global.
// 10 ms in 0.1 ns units — the per-cluster int32 field caps at ~214 ms so
// the practical tolerance must stay well inside that range. Tune after
// Phase 8 measurement.
const PlausibilityToleranceQ01ns int64 = 100_000_000

func (k msgServer) CommitSyncBlock(goCtx context.Context, msg *types.MsgCommitSyncBlock) (*types.MsgCommitSyncBlockResponse, error) {
	ctx := sdk.UnwrapSDKContext(goCtx)

	params := k.Keeper.GetParams(ctx)
	body := msg.Body

	// (1) Proposer must be in the current delegate set.
	if !k.Keeper.HasDelegateAddress(ctx, msg.Proposer) {
		return nil, errorsmod.Wrapf(types.ErrProposerNotDelegate, "proposer=%s", msg.Proposer)
	}

	// (2) Each cluster_table.head_id must map to a delegate.
	for i, c := range body.ClusterTable {
		if !k.Keeper.HasHeadID(ctx, c.HeadId) {
			return nil, errorsmod.Wrapf(types.ErrUnknownClusterHead, "cluster_table[%d].head_id=%d", i, c.HeadId)
		}
	}

	// (3, 4) Length consistency.
	if body.Global.ClusterCount != uint32(len(body.ClusterTable)) {
		return nil, errorsmod.Wrapf(types.ErrClusterCountMismatch, "global=%d table=%d", body.Global.ClusterCount, len(body.ClusterTable))
	}
	if body.Global.MemberCount != uint32(len(body.MemberTable)) {
		return nil, errorsmod.Wrapf(types.ErrMemberCountMismatch, "global=%d table=%d", body.Global.MemberCount, len(body.MemberTable))
	}

	// Safety: bound the member_table size per block.
	if uint64(len(body.MemberTable)) > params.MaxMemberRecordsPerBlock {
		return nil, errorsmod.Wrapf(types.ErrTooManyMembers, "%d > %d", len(body.MemberTable), params.MaxMemberRecordsPerBlock)
	}

	// (5) Plausibility check (spec §III.B "plausibility check"): the asserted
	// global ref time should sit within tolerance of the median of cluster
	// head offsets relative to global. We project the cluster heads onto the
	// global timeline (head_time = global_ref + head_offset_to_global) and
	// require their median to round-trip to global_ref within tolerance.
	if len(body.ClusterTable) > 0 {
		median := medianHeadOffset(body.ClusterTable)
		// |median| <= tolerance ensures the head distribution is centered on global.
		if abs64(int64(median)) > PlausibilityToleranceQ01ns {
			return nil, errorsmod.Wrapf(types.ErrPlausibility,
				"median head_offset=%d exceeds tolerance=%d (q01ns)", median, PlausibilityToleranceQ01ns)
		}
	}

	// (6) Persist.
	snap := types.BltEpochSnapshot{
		EpochId:       msg.EpochId,
		Height:        ctx.BlockHeight(),
		Proposer:      msg.Proposer,
		RelayPathHash: msg.RelayPathHash,
		Body:          body,
	}
	if err := k.Keeper.SetLatestEpoch(ctx, snap); err != nil {
		return nil, fmt.Errorf("set latest epoch: %w", err)
	}
	if err := k.Keeper.SetEpochHistory(ctx, snap); err != nil {
		return nil, fmt.Errorf("set epoch history: %w", err)
	}

	// (7) Emit event.
	ctx.EventManager().EmitEvent(sdk.NewEvent(
		types.EventTypeBlockCommitted,
		sdk.NewAttribute(types.AttributeKeyEpochID, strconv.FormatUint(uint64(msg.EpochId), 10)),
		sdk.NewAttribute(types.AttributeKeyGlobalRefTimeQ01ns, strconv.FormatUint(body.Global.GlobalRefTimeQ01Ns, 10)),
		sdk.NewAttribute(types.AttributeKeyHeight, strconv.FormatInt(ctx.BlockHeight(), 10)),
		sdk.NewAttribute(types.AttributeKeyProposer, msg.Proposer),
		sdk.NewAttribute(types.AttributeKeyClusterCount, strconv.FormatUint(uint64(body.Global.ClusterCount), 10)),
		sdk.NewAttribute(types.AttributeKeyMemberCount, strconv.FormatUint(uint64(body.Global.MemberCount), 10)),
	))

	return &types.MsgCommitSyncBlockResponse{
		GlobalRefTimeQ01Ns: body.Global.GlobalRefTimeQ01Ns,
	}, nil
}

// medianHeadOffset returns the median of head_offset_to_global_q01ns over
// the cluster_table. Returns 0 for an empty slice (caller guards).
func medianHeadOffset(rows []types.BltClusterSummary) int32 {
	xs := make([]int32, len(rows))
	for i, r := range rows {
		xs[i] = r.HeadOffsetToGlobalQ01Ns
	}
	sort.Slice(xs, func(i, j int) bool { return xs[i] < xs[j] })
	mid := len(xs) / 2
	if len(xs)%2 == 1 {
		return xs[mid]
	}
	return (xs[mid-1] + xs[mid]) / 2
}

func abs64(x int64) int64 {
	if x < 0 {
		return -x
	}
	return x
}

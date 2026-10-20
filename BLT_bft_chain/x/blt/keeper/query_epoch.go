package keeper

import (
	"context"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"leochain/x/blt/types"
)

func (k Keeper) LatestEpoch(goCtx context.Context, req *types.QueryLatestEpochRequest) (*types.QueryLatestEpochResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "invalid request")
	}
	ctx := sdk.UnwrapSDKContext(goCtx)
	snap, ok := k.GetLatestEpoch(ctx)
	if !ok {
		return nil, status.Error(codes.NotFound, types.ErrNoLatestEpoch.Error())
	}
	return &types.QueryLatestEpochResponse{Snapshot: snap}, nil
}

func (k Keeper) EpochHistory(goCtx context.Context, req *types.QueryEpochHistoryRequest) (*types.QueryEpochHistoryResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "invalid request")
	}
	ctx := sdk.UnwrapSDKContext(goCtx)
	snap, ok := k.GetEpochHistory(ctx, req.EpochId)
	if !ok {
		return nil, status.Error(codes.NotFound, types.ErrEpochNotFound.Error())
	}
	return &types.QueryEpochHistoryResponse{Snapshot: snap}, nil
}

// epochRangeDefaultLimit caps a range query that did not ask for a limit, and
// epochRangeMaxLimit caps one that asked for too much. A rejoining node walks
// the gap in pages rather than pulling unbounded state in one request, and the
// response says when it was truncated so the caller continues from the last
// height it received instead of assuming it saw everything.
const (
	epochRangeDefaultLimit = 100
	epochRangeMaxLimit     = 500
)

// EpochHistoryRange answers the query a node makes after a disconnection: give
// me every epoch committed between the last one I trust and now.
//
// This reads the height index rather than the epoch_id index. epoch_id is a u8
// on the wire and wraps every 256 rounds, so a gap longer than that cannot be
// enumerated by id at all -- two different epochs would answer to the same
// number. The height index is monotone for the life of the chain, which is what
// makes replaying an arbitrary gap possible.
func (k Keeper) EpochHistoryRange(goCtx context.Context, req *types.QueryEpochHistoryRangeRequest) (*types.QueryEpochHistoryRangeResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "invalid request")
	}
	if req.FromHeight < 0 || req.ToHeight < 0 {
		return nil, status.Error(codes.InvalidArgument, "heights must not be negative")
	}
	if req.ToHeight < req.FromHeight {
		return nil, status.Error(codes.InvalidArgument, "to_height precedes from_height")
	}
	limit := int(req.Limit)
	if limit <= 0 {
		limit = epochRangeDefaultLimit
	}
	if limit > epochRangeMaxLimit {
		limit = epochRangeMaxLimit
	}

	ctx := sdk.UnwrapSDKContext(goCtx)
	out := make([]types.BltEpochSnapshot, 0, limit)
	truncated := false
	k.IterateEpochHistoryByHeight(ctx, req.FromHeight, req.ToHeight,
		func(snap types.BltEpochSnapshot) bool {
			if len(out) == limit {
				// One past the page: report the window as incomplete rather
				// than silently returning a short answer.
				truncated = true
				return false
			}
			out = append(out, snap)
			return true
		})
	return &types.QueryEpochHistoryRangeResponse{Snapshots: out, Truncated: truncated}, nil
}

func (k Keeper) DelegateSet(goCtx context.Context, req *types.QueryDelegateSetRequest) (*types.QueryDelegateSetResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "invalid request")
	}
	ctx := sdk.UnwrapSDKContext(goCtx)
	set := k.GetDelegateSet(ctx)
	return &types.QueryDelegateSetResponse{DelegateSet: set}, nil
}

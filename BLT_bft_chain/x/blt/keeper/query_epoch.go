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

func (k Keeper) DelegateSet(goCtx context.Context, req *types.QueryDelegateSetRequest) (*types.QueryDelegateSetResponse, error) {
	if req == nil {
		return nil, status.Error(codes.InvalidArgument, "invalid request")
	}
	ctx := sdk.UnwrapSDKContext(goCtx)
	set := k.GetDelegateSet(ctx)
	return &types.QueryDelegateSetResponse{DelegateSet: set}, nil
}

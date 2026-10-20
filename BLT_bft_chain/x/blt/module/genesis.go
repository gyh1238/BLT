package blt

import (
	sdk "github.com/cosmos/cosmos-sdk/types"

	"leochain/x/blt/keeper"
	"leochain/x/blt/types"
)

// InitGenesis initializes the module's state from a provided genesis state.
func InitGenesis(ctx sdk.Context, k keeper.Keeper, genState types.GenesisState) {
	if err := k.SetParams(ctx, genState.Params); err != nil {
		panic(err)
	}
	if err := k.SetDelegateSet(ctx, genState.InitialDelegates); err != nil {
		panic(err)
	}
}

// ExportGenesis returns the module's exported genesis.
func ExportGenesis(ctx sdk.Context, k keeper.Keeper) *types.GenesisState {
	return &types.GenesisState{
		Params:           k.GetParams(ctx),
		InitialDelegates: k.GetDelegateSet(ctx),
	}
}

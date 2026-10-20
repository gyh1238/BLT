package keeper

import (
	"leochain/x/blt/types"
)

var _ types.QueryServer = Keeper{}

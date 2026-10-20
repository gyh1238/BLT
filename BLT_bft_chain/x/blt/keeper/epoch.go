package keeper

import (
	"context"

	"github.com/cosmos/cosmos-sdk/runtime"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"leochain/x/blt/types"
)

// GetLatestEpoch returns the most recently finalized epoch snapshot, if any.
func (k Keeper) GetLatestEpoch(ctx context.Context) (types.BltEpochSnapshot, bool) {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz := store.Get(types.LatestEpochKey)
	if bz == nil {
		return types.BltEpochSnapshot{}, false
	}
	var snap types.BltEpochSnapshot
	k.cdc.MustUnmarshal(bz, &snap)
	return snap, true
}

// SetLatestEpoch persists the snapshot as the current epoch tip.
func (k Keeper) SetLatestEpoch(ctx context.Context, snap types.BltEpochSnapshot) error {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz, err := k.cdc.Marshal(&snap)
	if err != nil {
		return err
	}
	store.Set(types.LatestEpochKey, bz)
	return nil
}

// GetEpochHistory looks up a past epoch snapshot by id.
func (k Keeper) GetEpochHistory(ctx context.Context, epochID uint32) (types.BltEpochSnapshot, bool) {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz := store.Get(types.EpochHistoryKey(epochID))
	if bz == nil {
		return types.BltEpochSnapshot{}, false
	}
	var snap types.BltEpochSnapshot
	k.cdc.MustUnmarshal(bz, &snap)
	return snap, true
}

// SetEpochHistory appends a past epoch snapshot keyed by its epoch_id.
func (k Keeper) SetEpochHistory(ctx context.Context, snap types.BltEpochSnapshot) error {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz, err := k.cdc.Marshal(&snap)
	if err != nil {
		return err
	}
	store.Set(types.EpochHistoryKey(snap.EpochId), bz)
	return nil
}

// SetEpochHistoryByHeight stores a snapshot under the height index.
func (k Keeper) SetEpochHistoryByHeight(ctx context.Context, snap types.BltEpochSnapshot) error {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz, err := k.cdc.Marshal(&snap)
	if err != nil {
		return err
	}
	store.Set(types.EpochHistoryByHeightKey(snap.Height), bz)
	return nil
}

// GetEpochHistoryByHeight returns the snapshot committed at a given height.
func (k Keeper) GetEpochHistoryByHeight(ctx context.Context, height int64) (types.BltEpochSnapshot, bool) {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz := store.Get(types.EpochHistoryByHeightKey(height))
	if bz == nil {
		return types.BltEpochSnapshot{}, false
	}
	var snap types.BltEpochSnapshot
	k.cdc.MustUnmarshal(bz, &snap)
	return snap, true
}

// IterateEpochHistoryByHeight walks committed epochs with
// fromHeight <= height <= toHeight in ascending order, which is exactly the
// replay a node performs after a disconnection: start from the last snapshot it
// trusts, take each subsequent epoch in order. Iteration stops early if fn
// returns false.
//
// Named for the index it reads rather than for the query it serves, because the
// gRPC method EpochHistoryRange is a method on this same Keeper and the two
// cannot share a name.
func (k Keeper) IterateEpochHistoryByHeight(ctx context.Context, fromHeight, toHeight int64,
	fn func(types.BltEpochSnapshot) bool) {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	start := types.EpochHistoryByHeightKey(fromHeight)
	// The iterator end is exclusive, so extend past the final key we want.
	end := types.EpochHistoryByHeightKey(toHeight + 1)
	it := store.Iterator(start, end)
	defer it.Close()
	for ; it.Valid(); it.Next() {
		var snap types.BltEpochSnapshot
		k.cdc.MustUnmarshal(it.Value(), &snap)
		if !fn(snap) {
			return
		}
	}
}

// GetDelegateSet returns the current round's delegates (cluster heads).
func (k Keeper) GetDelegateSet(ctx context.Context) types.BltDelegateSet {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz := store.Get(types.DelegateSetKey)
	if bz == nil {
		return types.BltDelegateSet{}
	}
	var set types.BltDelegateSet
	k.cdc.MustUnmarshal(bz, &set)
	return set
}

// SetDelegateSet stores the active delegate set.
func (k Keeper) SetDelegateSet(ctx context.Context, set types.BltDelegateSet) error {
	store := runtime.KVStoreAdapter(k.storeService.OpenKVStore(ctx))
	bz, err := k.cdc.Marshal(&set)
	if err != nil {
		return err
	}
	store.Set(types.DelegateSetKey, bz)
	return nil
}

// HasDelegateAddress reports whether the given address is in the active set.
//
// The genesis field is called validator_address and scripts/init_n_validators.sh
// fills it from the gentx, i.e. with an operator address (cosmosvaloper1...).
// MsgCommitSyncBlock, however, is signed by, and ValidateBasic checks, the
// account address (cosmos1...) of the same key, so a literal string compare can
// never match a genesis-initialised chain. Accept either form: the operator
// address and its account address share the same 20 address bytes.
func (k Keeper) HasDelegateAddress(ctx context.Context, addr string) bool {
	set := k.GetDelegateSet(ctx)
	for _, d := range set.Delegates {
		if d.ValidatorAddress == addr {
			return true
		}
		if acc, ok := accAddressOfValoper(d.ValidatorAddress); ok && acc == addr {
			return true
		}
	}
	return false
}

// accAddressOfValoper converts a bech32 operator address into the account
// address that signs on its behalf. Reports false for anything that is not a
// valid operator address (including an account address, already handled above).
func accAddressOfValoper(s string) (string, bool) {
	valAddr, err := sdk.ValAddressFromBech32(s)
	if err != nil {
		return "", false
	}
	return sdk.AccAddress(valAddr).String(), true
}

// HasHeadID reports whether the given head_id appears in the active set.
func (k Keeper) HasHeadID(ctx context.Context, headID uint32) bool {
	set := k.GetDelegateSet(ctx)
	for _, d := range set.Delegates {
		if d.HeadId == headID {
			return true
		}
	}
	return false
}

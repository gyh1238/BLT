package keeper

import (
	"context"

	"github.com/cosmos/cosmos-sdk/runtime"

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
func (k Keeper) HasDelegateAddress(ctx context.Context, addr string) bool {
	set := k.GetDelegateSet(ctx)
	for _, d := range set.Delegates {
		if d.ValidatorAddress == addr {
			return true
		}
	}
	return false
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

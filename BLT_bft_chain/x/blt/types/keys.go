package types

import "encoding/binary"

const (
	// ModuleName defines the module name.
	ModuleName = "blt"

	// StoreKey defines the primary module store key.
	StoreKey = ModuleName

	// MemStoreKey defines the in-memory store key.
	MemStoreKey = "mem_blt"
)

// KV store keys.
var (
	ParamsKey           = []byte{0x01}
	LatestEpochKey      = []byte{0x02}
	DelegateSetKey      = []byte{0x03}
	EpochHistoryPrefix  = []byte{0x04}

	// EpochHistoryByHeightPrefix indexes the same snapshots by block height.
	// epoch_id is a u8-range wrapping counter, so EpochHistoryKey overwrites
	// every 256 rounds and cannot express "the round after this one". Height is
	// strictly increasing for the life of the chain, so this index is the one
	// that gives the history an order, which is what a rejoining node needs to
	// walk the gap it missed.
	EpochHistoryByHeightPrefix = []byte{0x05}
)

// EpochHistoryKey returns the KV key for a single past epoch snapshot.
// Layout: prefix(0x04) || big-endian uint32(epoch_id).
func EpochHistoryKey(epochID uint32) []byte {
	b := make([]byte, 1+4)
	b[0] = EpochHistoryPrefix[0]
	binary.BigEndian.PutUint32(b[1:], epochID)
	return b
}

// EpochHistoryByHeightKey returns the KV key for a snapshot indexed by the
// height at which it was committed.
// Layout: prefix(0x05) || big-endian uint64(height).
// Big-endian keeps the KV iteration order equal to the chronological order, so
// a gap can be replayed with a single ascending range scan.
func EpochHistoryByHeightKey(height int64) []byte {
	b := make([]byte, 1+8)
	b[0] = EpochHistoryByHeightPrefix[0]
	binary.BigEndian.PutUint64(b[1:], uint64(height))
	return b
}

func KeyPrefix(p string) []byte {
	return []byte(p)
}

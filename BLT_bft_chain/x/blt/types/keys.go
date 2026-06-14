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
)

// EpochHistoryKey returns the KV key for a single past epoch snapshot.
// Layout: prefix(0x04) || big-endian uint32(epoch_id).
func EpochHistoryKey(epochID uint32) []byte {
	b := make([]byte, 1+4)
	b[0] = EpochHistoryPrefix[0]
	binary.BigEndian.PutUint32(b[1:], epochID)
	return b
}

func KeyPrefix(p string) []byte {
	return []byte(p)
}

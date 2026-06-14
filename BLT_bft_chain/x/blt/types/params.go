package types

import (
	"fmt"

	paramtypes "github.com/cosmos/cosmos-sdk/x/params/types"
)

var _ paramtypes.ParamSet = (*Params)(nil)

// Spec §2 / §4.5 defaults.
const (
	DefaultClusterCount             uint32 = 12
	DefaultEpochLengthMs            uint32 = 3500
	DefaultMaxMemberRecordsPerBlock uint64 = 16384
)

// ParamKeyTable is retained for legacy x/params interop.
func ParamKeyTable() paramtypes.KeyTable {
	return paramtypes.NewKeyTable().RegisterParamSet(&Params{})
}

// NewParams creates a new Params instance.
func NewParams(clusterCount uint32, epochLengthMs uint32, maxMemberRecords uint64) Params {
	return Params{
		ClusterCount:                clusterCount,
		EpochLengthMs:               epochLengthMs,
		MaxMemberRecordsPerBlock:    maxMemberRecords,
	}
}

// DefaultParams returns the default Params per spec §4.5.
func DefaultParams() Params {
	return NewParams(DefaultClusterCount, DefaultEpochLengthMs, DefaultMaxMemberRecordsPerBlock)
}

// ParamSetPairs returns an empty pair set; the module persists params via
// its own GetParams/SetParams (x/params not used directly).
func (p *Params) ParamSetPairs() paramtypes.ParamSetPairs {
	return paramtypes.ParamSetPairs{}
}

// Validate checks the parameter ranges.
func (p Params) Validate() error {
	if p.ClusterCount == 0 {
		return fmt.Errorf("cluster_count must be > 0")
	}
	if p.ClusterCount > 255 {
		return fmt.Errorf("cluster_count must fit in u8 (got %d)", p.ClusterCount)
	}
	if p.EpochLengthMs == 0 {
		return fmt.Errorf("epoch_length_ms must be > 0")
	}
	if p.MaxMemberRecordsPerBlock == 0 {
		return fmt.Errorf("max_member_records_per_block must be > 0")
	}
	return nil
}

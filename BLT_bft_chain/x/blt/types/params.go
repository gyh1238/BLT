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

	// Demo self-gen (EndBlocker) defaults — previously hardcoded in abci.go.
	DefaultMembersPerCluster uint32 = 683  // README: ~683 per cluster
	DefaultNominalRmseMilliNs uint32 = 6700 // README nominal 6.7 ns
)

// ParamKeyTable is retained for legacy x/params interop.
func ParamKeyTable() paramtypes.KeyTable {
	return paramtypes.NewKeyTable().RegisterParamSet(&Params{})
}

// NewParams creates a new Params instance.
func NewParams(clusterCount uint32, epochLengthMs uint32, maxMemberRecords uint64,
	membersPerCluster uint32, nominalRmseMilliNs uint32) Params {
	return Params{
		ClusterCount:             clusterCount,
		EpochLengthMs:            epochLengthMs,
		MaxMemberRecordsPerBlock: maxMemberRecords,
		MembersPerCluster:        membersPerCluster,
		NominalRmseMilliNs:       nominalRmseMilliNs,
	}
}

// DefaultParams returns the default Params per spec §4.5.
func DefaultParams() Params {
	return NewParams(DefaultClusterCount, DefaultEpochLengthMs, DefaultMaxMemberRecordsPerBlock,
		DefaultMembersPerCluster, DefaultNominalRmseMilliNs)
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
	if p.MembersPerCluster == 0 {
		return fmt.Errorf("members_per_cluster must be > 0")
	}
	if p.NominalRmseMilliNs == 0 {
		return fmt.Errorf("nominal_rmse_milli_ns must be > 0")
	}
	return nil
}

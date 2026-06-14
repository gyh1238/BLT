package types

// DONTCOVER

import (
	sdkerrors "cosmossdk.io/errors"
)

// x/blt module sentinel errors.
var (
	ErrInvalidSigner       = sdkerrors.Register(ModuleName, 1100, "expected gov account as only signer for proposal message")
	ErrProposerNotDelegate = sdkerrors.Register(ModuleName, 1101, "proposer is not a member of the current delegate set")
	ErrUnknownClusterHead  = sdkerrors.Register(ModuleName, 1102, "cluster head_id is not present in the current delegate set")
	ErrClusterCountMismatch = sdkerrors.Register(ModuleName, 1103, "global.cluster_count does not match cluster_table length")
	ErrMemberCountMismatch = sdkerrors.Register(ModuleName, 1104, "global.member_count does not match member_table length")
	ErrTooManyMembers      = sdkerrors.Register(ModuleName, 1105, "member_table exceeds max_member_records_per_block")
	ErrInvalidRelayPathHash = sdkerrors.Register(ModuleName, 1106, "relay_path_hash must be 32 bytes")
	ErrEpochNotFound       = sdkerrors.Register(ModuleName, 1107, "epoch snapshot not found")
	ErrNoLatestEpoch       = sdkerrors.Register(ModuleName, 1108, "no latest epoch committed yet")
	ErrPlausibility        = sdkerrors.Register(ModuleName, 1109, "global_ref_time is implausible against cluster head offsets")
)

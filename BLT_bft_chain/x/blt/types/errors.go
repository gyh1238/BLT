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

	// Stateful (ledger-dependent) validation errors. Unlike 1102-1109 these
	// cannot be decided from the message alone: they compare the proposal
	// against state the chain already agreed on.
	ErrNonMonotonicTime = sdkerrors.Register(ModuleName, 1110, "global_ref_time must advance past the previously committed epoch")
	ErrStaleRound       = sdkerrors.Register(ModuleName, 1111, "epoch was already committed at this height or later")
	ErrRefTimeSkew      = sdkerrors.Register(ModuleName, 1112, "global_ref_time disagrees with the consensus block time beyond tolerance")
	ErrDuplicateClusterHead = sdkerrors.Register(ModuleName, 1113, "cluster_table names the same head_id more than once")
	ErrEpochIdNotAdvancing  = sdkerrors.Register(ModuleName, 1114, "epoch_id must be 1..128 ahead of the previously committed epoch (mod 256)")
)

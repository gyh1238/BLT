package types

// Event types and attribute keys emitted by x/blt (spec §4.4).
const (
	EventTypeBlockCommitted = "blt_block_committed"

	AttributeKeyEpochID            = "epoch_id"
	AttributeKeyGlobalRefTimeQ01ns = "global_ref_time_q01ns"
	AttributeKeyHeight             = "height"
	AttributeKeyProposer           = "proposer"
	AttributeKeyClusterCount       = "cluster_count"
	AttributeKeyMemberCount        = "member_count"
)

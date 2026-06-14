package blt

import (
	autocliv1 "cosmossdk.io/api/cosmos/autocli/v1"

	modulev1 "leochain/api/leochain/blt"
)

// AutoCLIOptions implements the autocli.HasAutoCLIConfig interface.
func (am AppModule) AutoCLIOptions() *autocliv1.ModuleOptions {
	return &autocliv1.ModuleOptions{
		Query: &autocliv1.ServiceCommandDescriptor{
			Service: modulev1.Query_ServiceDesc.ServiceName,
			RpcCommandOptions: []*autocliv1.RpcCommandOptions{
				{
					RpcMethod: "Params",
					Use:       "params",
					Short:     "Shows the parameters of the module",
				},
				{
					RpcMethod: "LatestEpoch",
					Use:       "latest-epoch",
					Short:     "Returns the most recently finalized BLT epoch snapshot",
				},
				{
					RpcMethod:      "EpochHistory",
					Use:            "epoch-history [epoch-id]",
					Short:          "Returns a past epoch snapshot by id",
					PositionalArgs: []*autocliv1.PositionalArgDescriptor{{ProtoField: "epoch_id"}},
				},
				{
					RpcMethod: "DelegateSet",
					Use:       "delegate-set",
					Short:     "Returns the active 12 cluster-head delegates",
				},
				// this line is used by ignite scaffolding # autocli/query
			},
		},
		Tx: &autocliv1.ServiceCommandDescriptor{
			Service:              modulev1.Msg_ServiceDesc.ServiceName,
			EnhanceCustomCommand: true, // only required if you want to use the custom command
			RpcCommandOptions: []*autocliv1.RpcCommandOptions{
				{
					RpcMethod: "UpdateParams",
					Skip:      true, // skipped because authority gated
				},
				{
					RpcMethod: "CommitSyncBlock",
					// body is a complex BltBlockBody; the off-chain proposer
					// submits via gRPC/Tx builder rather than CLI. A bespoke
					// `tx blt commit-sync-block-from-file` command (Phase 8)
					// will accept a JSON-encoded body.
					Skip: true,
				},
				// this line is used by ignite scaffolding # autocli/tx
			},
		},
	}
}

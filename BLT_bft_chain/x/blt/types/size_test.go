package types

import (
	"testing"
)

// fullBody builds a worst-case MsgCommitSyncBlock body matching spec §10
// (12 cluster heads, 8192 members) so we can report the wire size to
// satisfy the §9.2 "X kB" placeholder.
func fullBody(nClusters, nMembers int) BltBlockBody {
	cluster := make([]BltClusterSummary, nClusters)
	for i := range cluster {
		cluster[i] = BltClusterSummary{
			ClusterId:               uint32(i),
			HeadId:                  uint32(100 + i),
			HeadOffsetToGlobalQ01Ns: int32(1000 * (i - nClusters/2)),
			MemberCount:             uint32(nMembers / nClusters),
			InlierCount:             uint32(nMembers / nClusters),
			MemberOffsetMeanQ01Ns:   1000,
			MemberOffsetVarQ01Ns2:   500,
		}
	}
	mem := make([]BltMemberRecord, nMembers)
	for i := range mem {
		mem[i] = BltMemberRecord{
			NodeId:             uint32(i + 1),
			ClusterId:          uint32(i % nClusters),
			OffsetToHeadQ01Ns:  int32((i % 1024) - 512),
			RespProbQ255:       250,
			TimeAccQ01Ns:       64,
			Flags:              1,
		}
	}
	return BltBlockBody{
		Global: BltBodyGlobal{
			GlobalRefTimeQ01Ns: 1_234_567_890,
			ClusterCount:       uint32(nClusters),
			MemberCount:        uint32(nMembers),
		},
		ClusterTable: cluster,
		MemberTable:  mem,
	}
}

func TestSize_FullPayload_12c_8192m(t *testing.T) {
	body := fullBody(12, 8192)
	msg := &MsgCommitSyncBlock{
		Proposer:      "cosmos1abcdefghijklmnopqrstuvwxyz0123456789ab",
		Body:          body,
		RelayPathHash: make([]byte, 32),
		EpochId:       42,
	}
	bz, err := msg.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Logf("MsgCommitSyncBlock wire size with 12 clusters + 8192 members: %d bytes (%.2f kB)",
		len(bz), float64(len(bz))/1024.0)
}

func TestSize_Empty(t *testing.T) {
	body := fullBody(12, 0)
	msg := &MsgCommitSyncBlock{
		Proposer:      "cosmos1abcdefghijklmnopqrstuvwxyz0123456789ab",
		Body:          body,
		RelayPathHash: make([]byte, 32),
		EpochId:       42,
	}
	bz, err := msg.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Logf("MsgCommitSyncBlock wire size with 12 clusters + 0 members: %d bytes", len(bz))
}

func TestSize_Sampled(t *testing.T) {
	for _, n := range []int{0, 12, 256, 1024, 4096, 8192} {
		body := fullBody(12, n)
		msg := &MsgCommitSyncBlock{
			Proposer:      "cosmos1abcdefghijklmnopqrstuvwxyz0123456789ab",
			Body:          body,
			RelayPathHash: make([]byte, 32),
			EpochId:       42,
		}
		bz, err := msg.Marshal()
		if err != nil {
			t.Fatalf("marshal n=%d: %v", n, err)
		}
		t.Logf("members=%d -> %d bytes (%.2f kB)", n, len(bz), float64(len(bz))/1024.0)
	}
}

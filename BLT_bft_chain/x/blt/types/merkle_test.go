package types

import (
	"testing"
)

func members(n int) []BltMemberRecord {
	out := make([]BltMemberRecord, n)
	for i := range out {
		out[i] = BltMemberRecord{
			NodeId: uint32(i + 1), ClusterId: uint32(i % 12),
			OffsetToHeadQ01Ns: int32((i % 1024) - 512),
			RespProbQ255:      250, TimeAccQ01Ns: 64, Flags: 1,
		}
	}
	return out
}

// Every member of a table must be able to prove its own record against the root,
// at every tree size -- including the odd ones, where the promotion rule applies.
func TestMemberProof_RoundTrip(t *testing.T) {
	for _, n := range []int{1, 2, 3, 5, 8, 12, 17, 64, 100} {
		recs := members(n)
		root, err := MemberRoot(recs)
		if err != nil {
			t.Fatalf("n=%d root: %v", n, err)
		}
		for _, r := range recs {
			rec, proof, err := ProveMember(recs, r.NodeId)
			if err != nil {
				t.Fatalf("n=%d node=%d prove: %v", n, r.NodeId, err)
			}
			if !VerifyMember(root, rec, proof) {
				t.Fatalf("n=%d node=%d failed to verify against its own root", n, r.NodeId)
			}
		}
	}
}

// A record that was not in the committed set must not verify, and neither must
// one whose contents were altered after the fact -- that is the whole point.
func TestMemberProof_RejectsTampering(t *testing.T) {
	recs := members(16)
	root, _ := MemberRoot(recs)
	rec, proof, err := ProveMember(recs, 7)
	if err != nil {
		t.Fatal(err)
	}
	if !VerifyMember(root, rec, proof) {
		t.Fatal("honest proof should verify")
	}

	altered := rec
	altered.OffsetToHeadQ01Ns += 1
	if VerifyMember(root, altered, proof) {
		t.Fatal("a modified offset still verified")
	}

	foreign := BltMemberRecord{NodeId: 9999, ClusterId: 0}
	if VerifyMember(root, foreign, proof) {
		t.Fatal("a record that was never committed still verified")
	}

	short := proof
	short.Siblings = short.Siblings[:len(short.Siblings)-1]
	if VerifyMember(root, rec, short) {
		t.Fatal("a truncated sibling path still verified")
	}
}

// The root commits to the set, not to the order a proposer serialised it in:
// two honest proposers with the same measurements must agree.
func TestMemberRoot_OrderIndependent(t *testing.T) {
	recs := members(32)
	forward, err := MemberRoot(recs)
	if err != nil {
		t.Fatal(err)
	}
	shuffled := make([]BltMemberRecord, len(recs))
	for i := range recs {
		shuffled[i] = recs[len(recs)-1-i]
	}
	reverse, err := MemberRoot(shuffled)
	if err != nil {
		t.Fatal(err)
	}
	if string(forward) != string(reverse) {
		t.Fatal("root depends on serialisation order")
	}
}

// One satellite must not be able to occupy two leaves.
func TestMemberRoot_RejectsDuplicateNode(t *testing.T) {
	recs := append(members(4), BltMemberRecord{NodeId: 2, ClusterId: 5})
	if _, err := MemberRoot(recs); err != ErrDuplicateMemberNode {
		t.Fatalf("want ErrDuplicateMemberNode, got %v", err)
	}
}

// An empty table commits to nothing rather than to the hash of nothing, so
// "no members" stays distinguishable on the wire.
func TestMemberRoot_EmptyIsEmpty(t *testing.T) {
	root, err := MemberRoot(nil)
	if err != nil || root != nil {
		t.Fatalf("want nil root and no error, got %v %v", root, err)
	}
}

// The size claim the paper would carry: a member verifies with a path that
// grows logarithmically, not with the table.
func TestMemberProof_SizeIsLogarithmic(t *testing.T) {
	recs := members(8192)
	_, proof, err := ProveMember(recs, 4096)
	if err != nil {
		t.Fatal(err)
	}
	bytes := len(MemberLeaf(recs[0])) + 32*len(proof.Siblings)
	if len(proof.Siblings) > 14 {
		t.Fatalf("8192 leaves should need at most 14 siblings, got %d", len(proof.Siblings))
	}
	t.Logf("8192 members: %d siblings, inclusion proof %d bytes", len(proof.Siblings), bytes)
}

from app.cooperative_review import DeviceReview,inspect_day
from app.harness.policy_digest import conflicting_service_claim,policy_digest


def test_individual_services_and_joint_response_obligation():
    r=inspect_day(DeviceReview(day="2024-03-20",baseline="fixed",demand="normal"))
    evidence=policy_digest("policy.multidevice",r)
    assert evidence["该方案实际充电服务达标"] and evidence["该方案实际冷链服务达标"] and not evidence["该方案实际响应交付达标"]
    assert conflicting_service_claim("响应结论表明无法同时保持充电与冷链。",r)
    assert not conflicting_service_claim("充电与冷链均达到服务要求，最低响应交付超过物理上界。",r)
    assert not conflicting_service_claim("在满足最低交付条件时，无法同时保持充电与冷链。",r)
    assert not conflicting_service_claim("无法同时保持充电、冷链和响应目标。",r)
    assert not conflicting_service_claim("这不代表无法同时保持充电与冷链。",r)

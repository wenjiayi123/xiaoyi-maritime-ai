"""Detect an English response request, preserving explicit Chinese-language preferences."""
import re


def english_goal(goal):
    if re.search(r"用中文|in Chinese|Mandarin reply",goal,re.I):
        return False
    if re.search(r"in English|用英文|用英语",goal,re.I):
        return True
    return len(re.findall("[a-zA-Z]",goal))>16 and not re.search("[\u4e00-\u9fff]",goal)

"""Builds prompts.json: 20 scored prompts, 4 extra reasoning prompts, 3 speed prompts,
1 warm-up prompt and 1 long (~1500 token) prompt. Deterministic."""
import json, random, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SYSTEM = "You are a helpful assistant. Answer accurately and concisely."

PASSAGE = (
    "In the spring of 2019, the public library in the small river town of Millbrook began lending something unusual: seeds. "
    "The idea came from Rosa Delgado, a retired science teacher who volunteered at the front desk. She noticed that many patrons "
    "borrowed gardening books but said that buying seed packets every year was expensive, especially for families on tight budgets. "
    "Delgado proposed a simple system. Members could take up to five packets of vegetable, herb or flower seeds each season at no cost. "
    "In return, they were encouraged, but not required, to let a few plants go to seed at the end of the summer and bring some of "
    "those seeds back to the library. The first year was modest. The library started with about 400 donated packets stored in an old "
    "wooden card catalog, and roughly 120 households took part. Many returns were mislabeled or mixed, so volunteers held evening "
    "workshops on how to dry, sort and label seeds properly. By 2022, the program had grown to more than 600 participating households "
    "and the collection included over 90 varieties, several of them local tomatoes and beans that had been grown in the valley for "
    "generations. Not everything went smoothly. Some seeds cross-pollinated and produced plants that looked nothing like the label "
    "promised, and the library had to add a warning card explaining which crops are easy to save and which are not. A small group of "
    "residents also worried that the program distracted staff from traditional library work. Supporters argue that the benefits are "
    "clear. The seed library has brought new visitors through the doors, connected older gardeners with younger ones, and helped "
    "preserve plant varieties that might otherwise have disappeared. Other libraries in the region have since visited Millbrook to "
    "copy the model."
)

FINAL = " Show your working briefly, then end your reply with a line of the form 'Final answer: <answer>'."
CODE = " Reply with only the code in one ```python code block, no explanation."


def code_prompt(sig, desc):
    return f"Write a Python function `{sig}` that {desc}.{CODE}"


prompts = [
    # 4 general knowledge / explanation, rubric 0-2
    dict(id="G1", category="general", scoring="rubric",
         prompt="Explain why the sky is blue in 3 to 4 sentences for a high-school student."),
    dict(id="G2", category="general", scoring="rubric",
         prompt="What is the difference between RAM and storage (such as an SSD) in a computer? Answer in one short paragraph."),
    dict(id="G3", category="general", scoring="rubric",
         prompt="Briefly explain what inflation is and name two common causes of it."),
    dict(id="G4", category="general", scoring="rubric",
         prompt="What causes the seasons on Earth? Many people think it is the distance from the Sun; address that misconception in your answer."),
    # 2 summarisation, rubric + length check
    dict(id="S1", category="summarization", scoring="rubric+max_words", max_words=60,
         prompt=f"Summarize the following passage in at most 60 words.\n\nPassage:\n{PASSAGE}"),
    dict(id="S2", category="summarization", scoring="rubric+max_words", max_words=19,
         prompt=f"Give a one-sentence summary of the following passage in under 20 words.\n\nPassage:\n{PASSAGE}"),
    # 4 math / logic, auto-checked by regex
    dict(id="M1", category="math", scoring="regex_number", answer=3.5,
         prompt="A shop sells pencils at 3 for $0.75. How much do 14 pencils cost, in dollars?" + FINAL),
    dict(id="M2", category="math", scoring="regex_number", answer=215,
         prompt="A train leaves at 9:40 and arrives at 13:15 on the same day. How many minutes does the trip take?" + FINAL),
    dict(id="M3", category="math", scoring="regex_number", answer=480,
         prompt="What is the sum of all integers from 1 to 60 (inclusive) that are divisible by 4?" + FINAL),
    dict(id="M4", category="logic", scoring="regex_word", answer="carol",
         prompt="Alice is older than Bob. Carol is younger than Bob. Dave is older than Alice. Who is the youngest of the four?" + FINAL),
    # 4 python tasks with unit tests
    dict(id="C1", category="code", scoring="unit_tests", func="is_palindrome",
         prompt=code_prompt("is_palindrome(s)", "returns True if the string s is a palindrome when you ignore case and every character that is not a letter or digit, and False otherwise"),
         tests=["assert is_palindrome('A man, a plan, a canal: Panama') == True",
                "assert is_palindrome('race a car') == False",
                "assert is_palindrome('') == True",
                "assert is_palindrome(\"No 'x' in Nixon\") == True",
                "assert is_palindrome('ab') == False"]),
    dict(id="C2", category="code", scoring="unit_tests", func="merge_intervals",
         prompt=code_prompt("merge_intervals(intervals)", "takes a list of [start, end] integer pairs, merges all overlapping or touching intervals, and returns the merged intervals as a list of [start, end] lists sorted by start"),
         tests=["_r = lambda x: [list(i) for i in x]",
                "assert _r(merge_intervals([[1,3],[2,6],[8,10],[15,18]])) == [[1,6],[8,10],[15,18]]",
                "assert _r(merge_intervals([[1,4],[4,5]])) == [[1,5]]",
                "assert _r(merge_intervals([])) == []",
                "assert _r(merge_intervals([[5,7],[1,2]])) == [[1,2],[5,7]]",
                "assert _r(merge_intervals([[1,10],[2,3],[4,5]])) == [[1,10]]"]),
    dict(id="C3", category="code", scoring="unit_tests", func="roman_to_int",
         prompt=code_prompt("roman_to_int(s)", "converts a Roman numeral string such as 'MCMXCIV' into an integer"),
         tests=["assert roman_to_int('III') == 3",
                "assert roman_to_int('LVIII') == 58",
                "assert roman_to_int('MCMXCIV') == 1994",
                "assert roman_to_int('IX') == 9",
                "assert roman_to_int('XL') == 40"]),
    dict(id="C4", category="code", scoring="unit_tests", func="second_largest",
         prompt=code_prompt("second_largest(nums)", "returns the second largest distinct value in a list of integers, or None if the list has fewer than two distinct values"),
         tests=["assert second_largest([3,1,4,4,5]) == 4",
                "assert second_largest([7,7,7]) is None",
                "assert second_largest([]) is None",
                "assert second_largest([-2,-1]) == -2",
                "assert second_largest([10, 9]) == 9"]),
    # 4 instruction following, auto-checked
    dict(id="I1", category="instruction", scoring="exact_bullets", n=3,
         prompt="List exactly 3 benefits of regular exercise as bullet points. Output only the 3 bullet points and nothing else."),
    dict(id="I2", category="instruction", scoring="json_only",
         prompt='Return only valid JSON, with no code fences and no extra text, describing the Eiffel Tower as an object with the keys "name" (a string), "year" (an integer, the year it was completed) and "tags" (a list of exactly 3 strings).'),
    dict(id="I3", category="instruction", scoring="max_words", max_words=39,
         prompt="In under 40 words, explain what a VPN does."),
    dict(id="I4", category="instruction", scoring="keyword_and_end", keyword="turquoise", end="END",
         prompt="Write two sentences about the ocean. You must use the word \"turquoise\", and the very last word of your reply must be END in capital letters."),
    # 2 multi-turn / system prompt, auto-checked
    dict(id="T1", category="multiturn", scoring="all_lowercase", min_words=10,
         system="You are a travel assistant. You must write every reply entirely in lowercase letters, with no capital letters at all.",
         prompt="Tell me about Paris in two sentences."),
    dict(id="T2", category="multiturn", scoring="contains_short", answer="94", max_words=10,
         history=[{"role": "user", "content": "My favourite number is 47. Please remember it."},
                  {"role": "assistant", "content": "Got it. Your favourite number is 47."},
                  {"role": "user", "content": "I am also learning Spanish this year."},
                  {"role": "assistant", "content": "That is great. Good luck with your Spanish studies!"}],
         prompt="What is my favourite number multiplied by 2? Reply with just the number."),
]

reasoning_extra = [
    dict(id="R1", category="math", scoring="regex_number", answer=5,
         prompt="A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost, in cents?" + FINAL),
    dict(id="R2", category="math", scoring="regex_number", answer=24,
         prompt="Tom has twice as many marbles as Jerry. After Tom gives Jerry 6 marbles, they have the same number. How many marbles did Tom have at first?" + FINAL),
    dict(id="R3", category="math", scoring="regex_number", answer=4,
         prompt="What is the remainder when 2 to the power of 20 is divided by 7?" + FINAL),
    dict(id="R4", category="logic", scoring="regex_number", answer=4,
         prompt="Five people sit in a row of seats numbered 1 to 5 from the left. Ann sits in seat 1. Ben sits next to Ann. Cara sits in seat 5. Dan does not sit next to Cara. Eve sits in the remaining seat. Which seat number does Eve sit in?" + FINAL),
]

speed = [
    dict(id="SP1", prompt="Write a detailed story of about 400 words about a lighthouse keeper who finds a message in a bottle."),
    dict(id="SP2", prompt="Explain in detail, step by step, how a household refrigerator keeps food cold."),
    dict(id="SP3", prompt="Describe the history of the printing press and its effects on European society."),
]

# Long prompt: ~1500 tokens of synthetic order records, then one question.
rng = random.Random(1234)
names = ["Maria", "Liam", "Aisha", "Kenji", "Sofia", "Omar", "Elena", "Noah", "Priya", "Lucas", "Mei", "Jonas"]
cities = ["Lyon", "Porto", "Leeds", "Graz", "Turin", "Ghent", "Bergen", "Cork"]
items = ["desk lamps", "notebooks", "coffee mugs", "phone chargers", "wool scarves", "water bottles", "pencil cases", "backpacks"]
months = ["January", "February", "March", "April", "May", "June"]
pays = ["by card", "in cash", "by bank transfer"]
lines, lyon = [], 0
for i in range(56):
    c = rng.choice(cities)
    lyon += c == "Lyon"
    lines.append(f"Order #{1001 + i}: {rng.choice(names)} from {c} ordered {rng.randint(1, 9)} {rng.choice(items)} on "
                 f"{rng.randint(1, 28)} {rng.choice(months)} and paid {rng.choice(pays)}; delivery took {rng.randint(2, 9)} days.")
long_prompt = ("Below is a log of customer orders.\n\n" + "\n".join(lines) +
               "\n\nQuestion: How many of these orders came from customers in Lyon? Reply with just the number.")

out = dict(system=SYSTEM, passage=PASSAGE, passage_words=len(PASSAGE.split()), prompts=prompts,
           reasoning_extra=reasoning_extra, speed=speed,
           warmup="Say hello in one short sentence.",
           long_prompt=dict(id="LONG", prompt=long_prompt, answer=lyon))
with open(os.path.join(ROOT, "prompts.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("prompts:", len(prompts), "passage words:", out["passage_words"], "lyon:", lyon, "long chars:", len(long_prompt))

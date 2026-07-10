from qa_tool.build_dummy_data import build_data

x = build_data(major_versions=10, max_runs=2)
print(len(x))

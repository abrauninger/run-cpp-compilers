import os
import re
import subprocess
import tempfile
from typing import NamedTuple

class FunctionDefinition(NamedTuple):
	name: str
	line_start_index: int
	line_count: int

class Instruction(NamedTuple):
	byte_offset: str
	operation: str
	operands: str

class CleanedInstruction(NamedTuple):
	label: str
	operation: str
	operands: str

class CleanedFunction(NamedTuple):
	name: str
	instructions: list

def parse_instruction(line):
	m = re.search('^\\s*(\\S+):\\s+(\\S+)\\s*(.*?)$', line)
	if (m):
		return Instruction(m.group(1), m.group(2), m.group(3))
	else:
		return None

def get_function_definitions(lines):
	# Scan through the 'dumpbin' output and identify function definitions.
	definitions = []
	line_index = 0

	while (line_index < len(lines)):
		m1 = re.search('^(.*):\\s*$', lines[line_index])
		if (m1):
			# We're in a function definition.
			function_name = m1.group(1)
			short_name = function_name

			m2 = re.search('^(\\S+)\\s+\\(.*\\)$', function_name)
			if (m2):
				short_name = m2.group(1)

			line_start_index = line_index;
			line_index += 1

			while (line_index < len(lines)):
				if (parse_instruction(lines[line_index]) == None):
					# We've reached the end of the function definition.
					line_count = line_index - line_start_index
					definitions.append(FunctionDefinition(short_name, line_start_index, line_count))
					break;
				line_index += 1

		line_index += 1

	return definitions

def find_function_definition(function_definitions, name):
	return next((definition for definition in function_definitions if definition.name == name), None)

def get_used_functions(lines, function_definitions, used_functions, current_function_names):
	for current_function_name in current_function_names:
		if (find_function_definition(used_functions, current_function_name)):
			return
		d = find_function_definition(function_definitions, current_function_name)
		if (d):
			used_functions.append(d)
			for line_index in range(d.line_start_index + 1, d.line_start_index + d.line_count):
				instruction = parse_instruction(lines[line_index])
				if (instruction.operation == 'call'):
					get_used_functions(lines, function_definitions, used_functions, [instruction.operands])

def is_jump(operation):
	return operation.startswith('j')

def get_cleaned_function(lines, function, next_label_index):
	instruction_pairs = []
	for line_index in range(function.line_start_index + 1, function.line_start_index + function.line_count):
		instruction = parse_instruction(lines[line_index])
		cleaned_instruction = CleanedInstruction(None, instruction.operation, instruction.operands)
		instruction_pairs.append((instruction, cleaned_instruction))
	for index in range(len(instruction_pairs)):
		raw_instruction = instruction_pairs[index][0]
		if (is_jump(raw_instruction.operation)):
			target_byte_offset = raw_instruction.operands
			target_instruction_index = None
			for target_index in range(len(instruction_pairs)):
				raw_target_instruction = instruction_pairs[target_index][0]
				if (raw_target_instruction.byte_offset == target_byte_offset):
					old_cleaned_instruction = instruction_pairs[index][1]
					old_cleaned_target_instruction = instruction_pairs[target_index][1]

					if (old_cleaned_target_instruction.label != None):
						label = old_cleaned_target_instruction.label
						new_cleaned_target_instruction = old_cleaned_target_instruction
					else:
						label = f'$L{next_label_index}'
						next_label_index += 1
						new_cleaned_target_instruction = CleanedInstruction(label, old_cleaned_target_instruction.operation, old_cleaned_target_instruction.operands)
					
					new_cleaned_instruction = CleanedInstruction(old_cleaned_instruction.label, old_cleaned_instruction.operation, label)
					
					instruction_pairs[index] = (raw_instruction, new_cleaned_instruction)
					instruction_pairs[target_index] = (raw_target_instruction, new_cleaned_target_instruction)

					break
	cleaned_instructions = map(lambda pair: pair[1], instruction_pairs)
	return CleanedFunction(function.name, cleaned_instructions);

def get_cleaned_functions(lines, function_definitions, used_functions):
	next_label_index = 0
	cleaned_functions = []

	for functionDefinition in function_definitions:
		function = find_function_definition(used_functions, functionDefinition.name)
		if (function):
			cleaned_functions.append(get_cleaned_function(lines, function, next_label_index))
	return cleaned_functions

def write_cleaned_function(output_file, cleaned_function):
	output_file.write(f'{cleaned_function.name}:\n')
	for instruction in cleaned_function.instructions:
		if (instruction.label):
			output_file.write(f'{instruction.label}:\n')
		output_file.write(f'  {instruction.operation}')
		for index in range(12 - len(instruction.operation)):
			output_file.write(' ')
		output_file.write(f'{instruction.operands}\n')
	output_file.write('\n')

def file_name_without_extension(file_name):
	return os.path.splitext(os.path.basename(file_name))[0]

def write_cleaned_disasm(output_file, lines, root_function_names):
	definitions = get_function_definitions(lines)
	used_functions = []
	get_used_functions(lines, definitions, used_functions, root_function_names)
	cleaned_functions = get_cleaned_functions(lines, definitions, used_functions)
	for cleaned_function in cleaned_functions:
		write_cleaned_function(output_file, cleaned_function)

def print_command(cmd_parts):
	for cmd_part in cmd_parts:
		print(cmd_part, end=' ')
	print('')

def compiler_exe_name(compiler_name):
	if (compiler_name == 'msvc'):
		return 'cl'
	elif (compiler_name == 'clang'):
		return 'clang++'
	elif (compiler_name == 'gcc'):
		return 'g++'
	else:
		raise Exception(f'Unknown compiler name: {compiler_name}')

def output_file_options(compiler_name, obj_dir, obj_file_name):
	if (compiler_name == 'msvc'):
		return [f'/Fo{obj_dir}\\'];
	else:
		return ['-o', f'{obj_dir}\\{obj_file_name}']

def generate_disassembly(compiler_name, cpp_file_name, disasm_file_name, include_directories, pound_defines, additional_compiler_options, root_function_names):
	cpp_file_nameWithoutExtension = file_name_without_extension(cpp_file_name)
	obj_file_name = f'{cpp_file_nameWithoutExtension}.obj'

	with tempfile.TemporaryDirectory() as obj_dir:
		cmd_parts = [compiler_exe_name(compiler_name)]
		cmd_parts += additional_compiler_options

		for include_directory in include_directories:
			cmd_parts.append('-I')
			cmd_parts.append(include_directory)

		for pound_define in pound_defines:
			cmd_parts.append('-D')
			cmd_parts.append(pound_define)

		for output_fileOption in output_file_options(compiler_name, obj_dir, obj_file_name):
			cmd_parts.append(output_fileOption)

		cmd_parts.append('-c')

		cmd_parts.append(cpp_file_name)

		print_command(cmd_parts)
		compiler_result = subprocess.run(cmd_parts, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		if (compiler_result.returncode != 0):
			print("!!!!!!!!!!!!!!")
			print('COMPILE ERRORS')
			print("!!!!!!!!!!!!!!")

		with tempfile.TemporaryFile('r') as disasm:
			dumpbin_cmd_parts = ['dumpbin', '/disasm:nobytes', f'{obj_dir}/{obj_file_name}']
			print_command(dumpbin_cmd_parts)
			subprocess.run(dumpbin_cmd_parts, stdout=disasm)

			cleaned_disasm = open(disasm_file_name, 'w')

			disasm.seek(0)
			lines = disasm.readlines()
			write_cleaned_disasm(output_file=cleaned_disasm, lines=lines, root_function_names=root_function_names)


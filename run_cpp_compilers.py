import os
import re
import subprocess
import tempfile
from typing import NamedTuple

class FunctionDefinition(NamedTuple):
	name: str
	lineStartIndex: int
	lineCount: int

class Instruction(NamedTuple):
	byteOffset: str
	operation: str
	operands: str

class CleanedInstruction(NamedTuple):
	label: str
	operation: str
	operands: str

class CleanedFunction(NamedTuple):
	name: str
	instructions: list

def parseInstruction(line):
	m = re.search('^\\s*(\\S+):\\s+(\\S+)\\s*(.*?)$', line)
	if (m):
		return Instruction(m.group(1), m.group(2), m.group(3))
	else:
		return None

def getFunctionDefinitions(lines):
	# Scan through the 'dumpbin' output and identify function definitions.
	definitions = []
	lineIndex = 0

	while (lineIndex < len(lines)):
		m1 = re.search('^(.*):\\s*$', lines[lineIndex])
		if (m1):
			# We're in a function definition.
			functionName = m1.group(1)
			shortName = functionName

			m2 = re.search('^(\\S+)\\s+\\(.*\\)$', functionName)
			if (m2):
				shortName = m2.group(1)

			lineStartIndex = lineIndex;
			lineIndex += 1

			while (lineIndex < len(lines)):
				if (parseInstruction(lines[lineIndex]) == None):
					# We've reached the end of the function definition.
					lineCount = lineIndex - lineStartIndex
					definitions.append(FunctionDefinition(shortName, lineStartIndex, lineCount))
					break;
				lineIndex += 1

		lineIndex += 1

	return definitions

def findFunctionDefinition(functionDefinitions, name):
	return next((definition for definition in functionDefinitions if definition.name == name), None)

def getUsedFunctions(lines, functionDefinitions, usedFunctions, currentFunctionNames):
	for currentFunctionName in currentFunctionNames:
		if (findFunctionDefinition(usedFunctions, currentFunctionName)):
			return
		d = findFunctionDefinition(functionDefinitions, currentFunctionName)
		if (d):
			usedFunctions.append(d)
			for lineIndex in range(d.lineStartIndex + 1, d.lineStartIndex + d.lineCount):
				instruction = parseInstruction(lines[lineIndex])
				if (instruction.operation == 'call'):
					getUsedFunctions(lines, functionDefinitions, usedFunctions, [instruction.operands])

def isJump(operation):
	return operation.startswith('j')

def getCleanedFunction(lines, function, nextLabelIndex):
	instructionPairs = []
	for lineIndex in range(function.lineStartIndex + 1, function.lineStartIndex + function.lineCount):
		instruction = parseInstruction(lines[lineIndex])
		cleanedInstruction = CleanedInstruction(None, instruction.operation, instruction.operands)
		instructionPairs.append((instruction, cleanedInstruction))
	for index in range(len(instructionPairs)):
		rawInstruction = instructionPairs[index][0]
		if (isJump(rawInstruction.operation)):
			targetByteOffset = rawInstruction.operands
			targetInstructionIndex = None
			for targetIndex in range(len(instructionPairs)):
				rawTargetInstruction = instructionPairs[targetIndex][0]
				if (rawTargetInstruction.byteOffset == targetByteOffset):
					oldCleanedInstruction = instructionPairs[index][1]
					oldCleanedTargetInstruction = instructionPairs[targetIndex][1]

					if (oldCleanedTargetInstruction.label != None):
						label = oldCleanedTargetInstruction.label
						newCleanedTargetInstruction = oldCleanedTargetInstruction
					else:
						label = f'$L{nextLabelIndex}'
						nextLabelIndex += 1
						newCleanedTargetInstruction = CleanedInstruction(label, oldCleanedTargetInstruction.operation, oldCleanedTargetInstruction.operands)
					
					newCleanedInstruction = CleanedInstruction(oldCleanedInstruction.label, oldCleanedInstruction.operation, label)
					
					instructionPairs[index] = (rawInstruction, newCleanedInstruction)
					instructionPairs[targetIndex] = (rawTargetInstruction, newCleanedTargetInstruction)

					break
	cleanedInstructions = map(lambda pair: pair[1], instructionPairs)
	return CleanedFunction(function.name, cleanedInstructions);

def getCleanedFunctions(lines, functionDefinitions, usedFunctions):
	nextLabelIndex = 0
	cleanedFunctions = []

	for functionDefinition in functionDefinitions:
		function = findFunctionDefinition(usedFunctions, functionDefinition.name)
		if (function):
			cleanedFunctions.append(getCleanedFunction(lines, function, nextLabelIndex))
	return cleanedFunctions

def writeCleanedFunction(outputFile, cleanedFunction):
	outputFile.write(f'{cleanedFunction.name}:\n')
	for instruction in cleanedFunction.instructions:
		if (instruction.label):
			outputFile.write(f'{instruction.label}:\n')
		outputFile.write(f'  {instruction.operation}')
		for index in range(12 - len(instruction.operation)):
			outputFile.write(' ')
		outputFile.write(f'{instruction.operands}\n')
	outputFile.write('\n')

def fileNameWithoutExtension(fileName):
	return os.path.splitext(os.path.basename(fileName))[0]

def writeCleanedDisasm(outputFile, lines, rootFunctionNames):
	definitions = getFunctionDefinitions(lines)
	usedFunctions = []
	getUsedFunctions(lines, definitions, usedFunctions, rootFunctionNames)
	cleanedFunctions = getCleanedFunctions(lines, definitions, usedFunctions)
	for cleanedFunction in cleanedFunctions:
		writeCleanedFunction(outputFile, cleanedFunction)

def printCommand(cmdParts):
	for cmdPart in cmdParts:
		print(cmdPart, end=' ')
	print('')

def compilerExeName(compilerName):
	if (compilerName == 'msvc'):
		return 'cl'
	elif (compilerName == 'clang'):
		return 'clang++'
	elif (compilerName == 'gcc'):
		return 'g++'
	else:
		raise Exception(f'Unknown compiler name: {compilerName}')

def outputFileOptions(compilerName, objDir, objFileName):
	if (compilerName == 'msvc'):
		return [f'/Fo{objDir}\\'];
	else:
		return ['-o', f'{objDir}\\{objFileName}']

def generate_disassembly(compilerName, cppFileName, disasmFileName, includeDirectories, poundDefines, additionalCompilerOptions, rootFunctionNames):
	cppFileNameWithoutExtension = fileNameWithoutExtension(cppFileName)
	objFileName = f'{cppFileNameWithoutExtension}.obj'

	with tempfile.TemporaryDirectory() as objDir:
		cmdParts = [compilerExeName(compilerName)]
		cmdParts += additionalCompilerOptions

		for includeDirectory in includeDirectories:
			cmdParts.append('-I')
			cmdParts.append(includeDirectory)

		for poundDefine in poundDefines:
			cmdParts.append('-D')
			cmdParts.append(poundDefine)

		for outputFileOption in outputFileOptions(compilerName, objDir, objFileName):
			cmdParts.append(outputFileOption)

		cmdParts.append('-c')

		cmdParts.append(cppFileName)

		printCommand(cmdParts)
		compilerResult = subprocess.run(cmdParts, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		if (compilerResult.returncode != 0):
			print("!!!!!!!!!!!!!!")
			print('COMPILE ERRORS')
			print("!!!!!!!!!!!!!!")

		with tempfile.TemporaryFile('r') as disasm:
			dumpbinCmdParts = ['dumpbin', '/disasm:nobytes', f'{objDir}/{objFileName}']
			printCommand(dumpbinCmdParts)
			subprocess.run(dumpbinCmdParts, stdout=disasm)

			cleanedDisasm = open(disasmFileName, 'w')

			disasm.seek(0)
			lines = disasm.readlines()
			writeCleanedDisasm(outputFile=cleanedDisasm, lines=lines, rootFunctionNames=rootFunctionNames)


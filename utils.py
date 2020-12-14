# -*- coding: utf-8 -*-

#-------------------------------------------------------------------------
# VK-GL-CTS Conformance Submission Verification
# ---------------------------------------------
#
# Copyright (c) 2020 The Khronos Group Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#-------------------------------------------------------------------------

import os
import subprocess
import tarfile
import tempfile

from report import *
from log_parser import StatusCode, BatchResultParser

ALLOWED_STATUS_CODES = set([
		StatusCode.PASS,
		StatusCode.NOT_SUPPORTED,
		StatusCode.QUALITY_WARNING,
		StatusCode.COMPATIBILITY_WARNING,
		StatusCode.WAIVER
	])

SUPPORTED_RELEASES	= ['vulkan-cts-[0-9]\.[0-9]\.[0-9]*\.[0-9]*',
					   'opengl-cts-4\.6\.[0-9]*\.[0-9]*',
					   'opengl-es-cts-3\.2\.[2-9]*\.[0-9]*']
WITHDRAWN_RELEASES	= ['vulkan-cts-1\.0\.0\.[0-9]*',
					   'vulkan-cts-1\.0\.1\.[0-9]*',
					   'vulkan-cts-1\.0\.2\.[0-9]*',
					   'vulkan-cts-1\.1\.0\.[0-9]*',
					   'vulkan-cts-1\.1\.1\.[0-9]*',
					   'vulkan-cts-1\.1\.2\.[0-9]*',
					   'vulkan-cts-1\.1\.3\.[0-9]*',
					   'vulkan-cts-1\.1\.4\.[0-9]*']
NOT_MASTER_DIR		= ['vulkan-cts-1\.0\.[0-9]*\.[0-9]*',
					   'vulkan-cts-1\.1\.0\.[0-9]*',
					   'vulkan-cts-1\.1\.1\.[0-9]*',
					   'vulkan-cts-1\.1\.2\.[0-9]*',
					   'vulkan-cts-1\.1\.3\.[0-9]*',
					   'vulkan-cts-1\.1\.4\.[0-9]*']
API_TYPE_DICT		= {'VK' : 'Vulkan', 'GL' : 'OpenGL', 'ES' : 'OpenGL ES'}
API_VERSION_DICT	= {'10' : '1.0', '11' : '1.1', '12' : '1.2',
					   '20' : '2.0',
					   '30' : '3.0', '31' : '3.1', '32' : '3.2', '33' : '3.3',
					   '40' : '4.0', '41' : '4.1', '42' : '4.2', '43' : '4.3',
					   '44' : '4.4', '45' : '4.5', '46' : '4.6'}
ES_SUPPORTED_VERSIONS = ['20', '30', '31', '32']
RELEASE_TAG_DICT	= {'VK' : 'vulkan-cts', 'ES' : 'opengl-es-cts', 'GL' : 'opengl-cts'}
KC_CTS_RELEASE		= ["opengl-es-cts-3\.2\.[2-3]\.[0-9]*", "opengl-cts-4\.6\.[0-9]*\.[0-9]*"]

class Verification:
	def __init__(self, packagePath, ctsPath, api, releaseTag):
		self.packagePath	= packagePath
		self.ctsPath		= ctsPath
		self.api			= api
		self.releaseTag		= releaseTag

def beginsWith (str, prefix):
	return str[:len(prefix)] == prefix

def readFile (filename):
	f = open(filename, 'rbU')
	data = f.read()
	f.close()
	return data

def untarPackage(report, pkgFile, dst):
	report.message("Unpacking ...", pkgFile)
	try:
		tar = tarfile.open(pkgFile)
		tar.extractall(dst)
		tar.close()
	except Exception as e:
		report.failure("Failed to unpack. Exception %s raised" % str(e), pkgFile)
		return False
	report.message("Unpacking done.", pkgFile)
	return True

g_workDirStack = []

def pushWorkingDir (path):
	oldDir = os.getcwd()
	os.chdir(path)
	g_workDirStack.append(oldDir)

def popWorkingDir ():
	assert len(g_workDirStack) > 0
	newDir = g_workDirStack[-1]
	g_workDirStack.pop()
	os.chdir(newDir)

def git (*args):
	process = subprocess.Popen(['git'] + list(args), stdout=subprocess.PIPE)
	output = process.communicate()[0]
	if process.returncode != 0:
		raise Exception("Failed to execute '%s', got %d" % (str(args), process.returncode))
	return output

def cloneCTS(dest):
	repos		= ['ssh://gerrit.khronos.org:29418/vk-gl-cts',
				   'https://github.com/KhronosGroup/VK-GL-CTS',
				   'git@gitlab.khronos.org:Tracker/vk-gl-cts.git',
				   'https://gitlab.khronos.org/Tracker/vk-gl-cts.git',
				   'https://gerrit.khronos.org/a/vk-gl-cts']
	success		= False
	print(dest)
	for repo in repos:
		try:
			git('clone', repo, dest)
		except Exception as e:
			print("Failed to clone %s. Trying the next repo." % repo)
		else:
			success = True
			break

	if not success:
		print("Failed to clone VK-GL-CTS. Verification will now stop.")
		sys.exit(RETURN_CODE_ERR)

def validateSource(ctsPath):
	if ctsPath == None:
		ctsPath = os.path.join(tempfile.gettempdir(), "VK-GL-CTS")
		cloneCTS(ctsPath)

	pushWorkingDir(ctsPath)
	try:
		result = git('rev-parse', '--is-inside-work-tree')
	except:
		sys.exit(RETURN_CODE_ERR)
	else:
		if result == "false":
			print("Path to VK-GL-CTS is not a git tree. Verification will now stop.")
			sys.exit(RETURN_CODE_ERR)
	popWorkingDir()

	return ctsPath

def checkoutReleaseTag(report, releaseTag):
	success = False
	try:
		git('checkout', releaseTag)
	except:
		report.failure("Failed to checkout release tag %s" % releaseTag)
	else:
		success = True
	return success

def readTestLog (filename):
	parser = BatchResultParser()
	return parser.parseFile(filename)

def verifyFileIntegrity(report, filename, info, gitSHA):

	anyError = False
	report.message("Verifying file integrity.", filename)

	report.message("Verifying sessionInfo")

	releaseNameKey	= "releaseName"
	if releaseNameKey not in info:
		anyError |= True
		report.failure("Test log is missing %s" % releaseNameKey)
	else:
		sha1 = info[releaseNameKey]
		if sha1 == 'git-' + gitSHA:
			report.passed("Test log %s matches the HEAD commit from git log: %s" % (releaseNameKey, gitSHA))
		else:
			anyError |= True
			report.failure("Test log %s doesn't match the HEAD commit from git log: %s" % (releaseNameKey, gitSHA))

	releaseIdKey	= "releaseId"
	if releaseIdKey not in info:
		anyError |= True
		report.failure("Test log is missing %s" % releaseIdKey)
	else:
		sha1 = info[releaseIdKey]
		if sha1 == '0x' + gitSHA[0:8]:
			report.passed("Test log %s matches the HEAD commit from git log: %s" % (releaseIdKey, gitSHA))
		else:
			anyError |= True
			report.failure("Test log %s doesn't match the HEAD commit from git log: %s" % (releaseIdKey, gitSHA))
	return anyError

def isSubmissionSupported(apiType, apiVersion):
	if apiType == "VK":
		return True
	if apiType == "GL":
		return True
	if apiType == "ES" and apiVersion in ES_SUPPORTED_VERSIONS:
		return True
	return False

def validateTestCasePresence(report, mustpass, results):
	# Verify that all results are present and valid
	anyError = False
	resultOrderOk = True
	caseNameToResultNdx = {}
	for ndx in range(len(results)):
		result = results[ndx]
		if not result in caseNameToResultNdx:
			caseNameToResultNdx[result.name] = ndx
		else:
			report.failure("Multiple results for " + result.name)
			anyError |= True

	failNum = 0
	for ndx in range(len(mustpass)):
		caseName = str(mustpass[ndx], 'utf-8')

		if caseName in caseNameToResultNdx:
			resultNdx	= caseNameToResultNdx[caseName]
			result		= results[resultNdx]

			if resultNdx != ndx:
				resultOrderOk = False

			if not result.statusCode in ALLOWED_STATUS_CODES:
				report.failure(result.name + ": " + result.statusCode)
				anyError |= True
		else:
			if failNum < 21:
				report.failure("Missing result for " + str(caseName, 'utf-8'))
				failNum += 1
			anyError |= True

	if failNum >= 21:
		report.message("More missing results found but only first 20 are reported")

	return anyError, resultOrderOk

def verifyTestLog (report, package, mustpass, fractionMustpass, gitSHA):
	# Mustpass case names must be unique
	assert len(mustpass) == len(set(mustpass))
	if fractionMustpass != None:
		assert len(fractionMustpass) == len(set(fractionMustpass))

	anyError		= False
	for key, filesList in package.testLogs.items():
		totalResults	= []
		isFractionResults = (len(filesList) > 1)

		addFullResults = True
		for testLogFile in filesList:
			filename = os.path.join(package.basePath, testLogFile)
			report.message("Reading results.", filename)
			results, info	= readTestLog(filename)
			anyError |= verifyFileIntegrity(report, filename, info, gitSHA)

			if isFractionResults:
				report.message("Verifying vk-fraction-mandatory-tests.txt results.", filename)
				anyErrorTmp, resultOrderOk = validateTestCasePresence(report, fractionMustpass, results)
				anyError |= anyErrorTmp

				if anyError:
					report.failure("Verification of vk-fraction-mandatory-tests.txt results FAILED", filename)
				else:
					report.passed("Verification of vk-fraction-mandatory-tests.txt results PASSED", filename)

			if addFullResults:
				totalResults += results
				addFullResults = False
			else:
				results = [r for r in results if r.name not in fractionMustpass]
				totalResults += results

		report.message("Verifying vk-default.txt results.")
		anyErrorTmp , resultOrderOk= validateTestCasePresence(report, mustpass, totalResults)
		anyError |= anyErrorTmp

		# Verify number of results
		if len(totalResults) != len(mustpass):
			report.failure("Wrong number of test results, expected %d, found %d" % (len(mustpass), len(totalResults)))
			anyError |= True

		if anyError:
			report.failure("Verification of vk-default.txt results FAILED")
		else:
			report.passed("Verification of vk-default.txt results PASSED")

	return anyError

def verifyTestLogES (report, filename, mustpass, gitSHA):
	# Mustpass case names must be unique
	assert len(mustpass) == len(set(mustpass))

	report.message("Reading results.", filename)
	results, info	= readTestLog(filename)
	anyError		= False
	resultOrderOk	= True

	anyError |= verifyFileIntegrity(report, filename, info, gitSHA)

	# Verify number of results
	if len(results) != len(mustpass):
		report.failure("Wrong number of test results, expected %d, found %d" % (len(mustpass), len(results)), filename)
		anyError |= True

	anyErrorTmp , resultOrderOk= validateTestCasePresence(report, mustpass, results)
	anyError |= anyErrorTmp

	if len(results) == len(mustpass) and not resultOrderOk:
		report.failure("Results are not in the expected order", filename)
		anyError |= True

	if anyError:
		report.failure("Verification of test results FAILED", filename)
	else:
		report.passed("Verification of test results PASSED", filename)

	return anyError

def readMustpass (report, filename):
	cases = []
	try:
		f = open(filename, 'rb')
	except Exception as e:
		report.failure("Failed to open %s" % filename)
		return False, cases
	for line in f:
		s = line.strip()
		if len(s) > 0:
			cases.append(s)
	return True, cases

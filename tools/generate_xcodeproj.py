#!/usr/bin/env python3
"""Generates ios-agent/SandstormAgent.xcodeproj/project.pbxproj.

The project is intentionally generated rather than hand-maintained: it uses
Xcode 16+ *synchronized root groups* (objectVersion 77) so new Swift files added
under Sources/Agent or Sources/Demo are picked up without touching the project
file.

Usage:
    python3 tools/generate_xcodeproj.py
    python3 tools/generate_xcodeproj.py --bundle-prefix com.company \
        --signing-style Manual --team ABCDE12345 \
        --demo-profile "Wildcard Dev" --agent-profile "Wildcard Dev"

Manual signing exists for locked-down machines where no Apple ID can be
added to Xcode: the profiles must already be installed.
"""
from __future__ import annotations

import argparse
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "ios-agent" / "SandstormAgent.xcodeproj"

NAMES = [
    "project", "mainGroup", "productsGroup", "syncAgent", "syncDemo",
    "demoTarget", "agentTarget", "demoProduct", "agentProduct",
    "demoSources", "demoFrameworks", "demoResources",
    "agentSources", "agentFrameworks", "agentResources",
    "projectConfigList", "demoConfigList", "agentConfigList",
    "projectDebug", "projectRelease", "demoDebug", "demoRelease",
    "agentDebug", "agentRelease",
    "dependency", "containerProxy",
]
ID = {name: f"{(index + 1) * 0x101:024X}" for index, name in enumerate(NAMES)}

DEPLOYMENT_TARGET = "16.0"
SWIFT_VERSION = "5.0"
DEMO_BUNDLE_ID = "com.sandstorm.demo"
AGENT_BUNDLE_ID = "com.sandstorm.agent"

AGENT_DEPENDENCY = f"""
				{ID['dependency']},
"""

PROJECT_COMMON = f"""
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				GCC_NO_COMMON_BLOCKS = YES;
				IPHONEOS_DEPLOYMENT_TARGET = {DEPLOYMENT_TARGET};
				SDKROOT = iphoneos;
				SWIFT_VERSION = {SWIFT_VERSION};
				TARGETED_DEVICE_FAMILY = "1,2";
"""

TEMPLATE = f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 77;
	objects = {{

/* Begin PBXFileReference section */
		{ID['demoProduct']} /* SandstormDemo.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = SandstormDemo.app; sourceTree = BUILT_PRODUCTS_DIR; }};
		{ID['agentProduct']} /* SandstormAgent.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = SandstormAgent.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};
/* End PBXFileReference section */

/* Begin PBXFileSystemSynchronizedRootGroup section */
		{ID['syncAgent']} /* Agent */ = {{isa = PBXFileSystemSynchronizedRootGroup; path = Sources/Agent; sourceTree = "<group>"; }};
		{ID['syncDemo']} /* Demo */ = {{isa = PBXFileSystemSynchronizedRootGroup; path = Sources/Demo; sourceTree = "<group>"; }};
/* End PBXFileSystemSynchronizedRootGroup section */

/* Begin PBXFrameworksBuildPhase section */
		{ID['demoFrameworks']} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{ID['agentFrameworks']} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		{ID['demoSources']} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{ID['agentSources']} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
/* End PBXSourcesBuildPhase section */

/* Begin PBXResourcesBuildPhase section */
		{ID['demoResources']} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
		{ID['agentResources']} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};
/* End PBXResourcesBuildPhase section */

/* Begin PBXGroup section */
		{ID['mainGroup']} = {{
			isa = PBXGroup;
			children = (
				{ID['syncDemo']} /* Demo */,
				{ID['syncAgent']} /* Agent */,
				{ID['productsGroup']} /* Products */,
			);
			sourceTree = "<group>";
		}};
		{ID['productsGroup']} /* Products */ = {{
			isa = PBXGroup;
			children = (
				{ID['demoProduct']} /* SandstormDemo.app */,
				{ID['agentProduct']} /* SandstormAgent.xctest */,
			);
			name = Products;
			sourceTree = "<group>";
		}};
/* End PBXGroup section */

/* Begin PBXContainerItemProxy section */
		{ID['containerProxy']} = {{
			isa = PBXContainerItemProxy;
			containerPortal = {ID['project']};
			proxyType = 1;
			remoteGlobalIDString = {ID['demoTarget']};
			remoteInfo = SandstormDemo;
		}};
/* End PBXContainerItemProxy section */

/* Begin PBXTargetDependency section */
		{ID['dependency']} = {{
			isa = PBXTargetDependency;
			target = {ID['demoTarget']};
			targetProxy = {ID['containerProxy']};
		}};
/* End PBXTargetDependency section */

/* Begin PBXNativeTarget section */
		{ID['demoTarget']} /* SandstormDemo */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {ID['demoConfigList']};
			buildPhases = (
				{ID['demoSources']},
				{ID['demoFrameworks']},
				{ID['demoResources']},
			);
			buildRules = ();
			dependencies = ();
			fileSystemSynchronizedGroups = (
				{ID['syncDemo']} /* Demo */,
			);
			name = SandstormDemo;
			productName = SandstormDemo;
			productReference = {ID['demoProduct']};
			productType = "com.apple.product-type.application";
		}};
		{ID['agentTarget']} /* SandstormAgent */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {ID['agentConfigList']};
			buildPhases = (
				{ID['agentSources']},
				{ID['agentFrameworks']},
				{ID['agentResources']},
			);
			buildRules = ();
			dependencies = ({AGENT_DEPENDENCY}			);
			fileSystemSynchronizedGroups = (
				{ID['syncAgent']} /* Agent */,
			);
			name = SandstormAgent;
			productName = SandstormAgent;
			productReference = {ID['agentProduct']};
			productType = "com.apple.product-type.bundle.ui-testing";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		{ID['project']} = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1600;
				LastUpgradeCheck = 1600;
				TargetAttributes = {{
					{ID['demoTarget']} = {{
						CreatedOnToolsVersion = 16.0;
					}};
					{ID['agentTarget']} = {{
						CreatedOnToolsVersion = 16.0;
					}};
				}};
			}};
			buildConfigurationList = {ID['projectConfigList']};
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = {ID['mainGroup']};
			minimizedProjectReferenceProxies = 1;
			preferredProjectObjectVersion = 77;
			productRefGroup = {ID['productsGroup']} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{ID['demoTarget']} /* SandstormDemo */,
				{ID['agentTarget']} /* SandstormAgent */,
			);
		}};
/* End PBXProject section */

/* Begin XCBuildConfiguration section */
		{ID['projectDebug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_TESTABILITY = YES;
				GCC_OPTIMIZATION_LEVEL = 0;
				ONLY_ACTIVE_ARCH = YES;
				SWIFT_ACTIVE_COMPILATION_CONDITIONS = "DEBUG $(inherited)";
				SWIFT_OPTIMIZATION_LEVEL = "-Onone";{PROJECT_COMMON}			}};
			name = Debug;
		}};
		{ID['projectRelease']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				SWIFT_COMPILATION_MODE = wholemodule;{PROJECT_COMMON}			}};
			name = Release;
		}};
		{ID['demoDebug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
				INFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
				MARKETING_VERSION = 0.1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {DEMO_BUNDLE_ID};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = YES;
			}};
			name = Debug;
		}};
		{ID['demoRelease']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
				INFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
				MARKETING_VERSION = 0.1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {DEMO_BUNDLE_ID};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = YES;
			}};
			name = Release;
		}};
		{ID['agentDebug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				GENERATE_INFOPLIST_FILE = YES;
				MARKETING_VERSION = 0.1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {AGENT_BUNDLE_ID};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = NO;
			}};
			name = Debug;
		}};
		{ID['agentRelease']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				GENERATE_INFOPLIST_FILE = YES;
				MARKETING_VERSION = 0.1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {AGENT_BUNDLE_ID};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = NO;
			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		{ID['projectConfigList']} = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{ID['projectDebug']} /* Debug */,
				{ID['projectRelease']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
		{ID['demoConfigList']} = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{ID['demoDebug']} /* Debug */,
				{ID['demoRelease']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
		{ID['agentConfigList']} = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{ID['agentDebug']} /* Debug */,
				{ID['agentRelease']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
/* End XCConfigurationList section */
	}};
	rootObject = {ID['project']};
}}
"""

DEMO_SCHEME_ENTRY = f"""         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "NO" buildForArchiving = "NO" buildForAnalyzing = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{ID['demoTarget']}"
               BuildableName = "SandstormDemo.app"
               BlueprintName = "SandstormDemo"
               ReferencedContainer = "container:SandstormAgent.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
"""

SCHEME = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1600" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "NO" buildForArchiving = "NO" buildForAnalyzing = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{ID['agentTarget']}"
               BuildableName = "SandstormAgent.xctest"
               BlueprintName = "SandstormAgent"
               ReferencedContainer = "container:SandstormAgent.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
{DEMO_SCHEME_ENTRY}      </BuildActionEntries>
   </BuildAction>
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = ""
      selectedLauncherIdentifier = "Xcode.IDEFoundation.Launcher.PosixSpawn"
      shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
         <TestableReference skipped = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{ID['agentTarget']}"
               BuildableName = "SandstormAgent.xctest"
               BlueprintName = "SandstormAgent"
               ReferencedContainer = "container:SandstormAgent.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = ""
      selectedLauncherIdentifier = "Xcode.IDEFoundation.Launcher.PosixSpawn"
      launchStyle = "0"
      useCustomWorkingDirectory = "NO"
      ignoresPersistentStateOnLaunch = "NO"
      debugDocumentVersioning = "YES"
      allowLocationSimulation = "YES">
   </LaunchAction>
   <AnalyzeAction buildConfiguration = "Debug"></AnalyzeAction>
   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES"></ArchiveAction>
</Scheme>
"""


AUTOMATIC_SIGNING = "CODE_SIGN_STYLE = Automatic;"


def _signing_block(style: str, team: str | None, profile: str | None) -> str:
    """Build settings replacing the default automatic-signing line."""
    lines = [f"CODE_SIGN_STYLE = {style};"]
    if team:
        lines.append(f"DEVELOPMENT_TEAM = {team};")
    if style == "Manual":
        # Without an explicit identity Xcode picks "iPhone Developer", which no
        # longer exists; "Apple Development" matches any modern dev certificate.
        lines.append('CODE_SIGN_IDENTITY = "Apple Development";')
        if profile:
            lines.append(f'PROVISIONING_PROFILE_SPECIFIER = "{profile}";')
    return "\n\t\t\t\t".join(lines)


def render(
    *,
    demo_bundle_id: str = DEMO_BUNDLE_ID,
    agent_bundle_id: str = AGENT_BUNDLE_ID,
    signing_style: str = "Automatic",
    team: str | None = None,
    demo_profile: str | None = None,
    agent_profile: str | None = None,
    include_demo: bool = True,
) -> str:
    """Renders project.pbxproj with the requested identifiers and signing."""
    project = TEMPLATE.replace(DEMO_BUNDLE_ID, demo_bundle_id).replace(
        AGENT_BUNDLE_ID, agent_bundle_id
    )
    if not include_demo:
        # Drop the agent's dependency on the demo app so the demo is never
        # built and therefore never needs a provisioning profile of its own.
        project = project.replace(AGENT_DEPENDENCY, "")
    if signing_style == "Automatic" and not team:
        return project

    # The four occurrences are, in order: demo Debug, demo Release,
    # agent Debug, agent Release.
    blocks = [
        _signing_block(signing_style, team, demo_profile),
        _signing_block(signing_style, team, demo_profile),
        _signing_block(signing_style, team, agent_profile),
        _signing_block(signing_style, team, agent_profile),
    ]
    parts = project.split(AUTOMATIC_SIGNING)
    if len(parts) != len(blocks) + 1:
        raise RuntimeError(
            f"Expected {len(blocks)} signing blocks in the template, found {len(parts) - 1}"
        )
    rendered = parts[0]
    for block, tail in zip(blocks, parts[1:]):
        rendered += block + tail
    return rendered


def write_project(**kwargs: object) -> pathlib.Path:
    """Writes project.pbxproj and the shared scheme; returns the project dir."""
    schemes = PROJECT_DIR / "xcshareddata" / "xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    (PROJECT_DIR / "project.pbxproj").write_text(render(**kwargs))  # type: ignore[arg-type]
    scheme = SCHEME
    if kwargs.get("include_demo") is False:
        scheme = scheme.replace(DEMO_SCHEME_ENTRY, "")
    (schemes / "SandstormAgent.xcscheme").write_text(scheme)
    return PROJECT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-prefix",
        default=None,
        help="Reverse-DNS prefix for both targets, e.g. com.company "
        "(yields <prefix>.sandstormdemo and <prefix>.sandstormagent)",
    )
    parser.add_argument("--demo-bundle-id", default=None)
    parser.add_argument("--agent-bundle-id", default=None)
    parser.add_argument("--signing-style", choices=["Automatic", "Manual"], default="Automatic")
    parser.add_argument("--team", default=None)
    parser.add_argument("--demo-profile", default=None, help="Profile name or UUID")
    parser.add_argument("--agent-profile", default=None, help="Profile name or UUID")
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="Do not build the bundled demo app, so only the agent needs signing",
    )
    args = parser.parse_args()

    demo = args.demo_bundle_id or (
        f"{args.bundle_prefix}.sandstormdemo" if args.bundle_prefix else DEMO_BUNDLE_ID
    )
    agent = args.agent_bundle_id or (
        f"{args.bundle_prefix}.sandstormagent" if args.bundle_prefix else AGENT_BUNDLE_ID
    )
    write_project(
        demo_bundle_id=demo,
        agent_bundle_id=agent,
        signing_style=args.signing_style,
        team=args.team,
        demo_profile=args.demo_profile,
        agent_profile=args.agent_profile,
        include_demo=not args.no_demo,
    )
    print(f"Wrote {PROJECT_DIR}")
    print(f"  demo  {demo}")
    print(f"  agent {agent}  (runner: {agent}.xctrunner)")


if __name__ == "__main__":
    main()

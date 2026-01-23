#!/usr/bin/env node

/**
 * Generate marketplace.json for Claude Code plugin distribution
 *
 * This script scans the skills/ directory and generates a marketplace.json
 * file that can be used to distribute skills via Claude Code's plugin system.
 *
 * Usage: node scripts/generate-marketplace.js [options]
 *
 * Options:
 *   --name <name>         Marketplace name (default: from package.json or "skills-marketplace")
 *   --owner <name>        Owner name (default: from package.json author or "Skills Team")
 *   --email <email>       Owner email (optional)
 *   --description <desc>  Marketplace description
 *   --output <path>       Output path (default: .claude-plugin/marketplace.json)
 *   --skills-dir <path>   Skills directory (default: skills)
 */

const fs = require('fs');
const path = require('path');

// Parse command line arguments
function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    name: null,
    owner: null,
    email: null,
    description: null,
    output: '.claude-plugin/marketplace.json',
    skillsDir: 'skills',
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--name':
        options.name = args[++i];
        break;
      case '--owner':
        options.owner = args[++i];
        break;
      case '--email':
        options.email = args[++i];
        break;
      case '--description':
        options.description = args[++i];
        break;
      case '--output':
        options.output = args[++i];
        break;
      case '--skills-dir':
        options.skillsDir = args[++i];
        break;
      case '--help':
        console.log(`
Usage: node scripts/generate-marketplace.js [options]

Options:
  --name <name>         Marketplace name (default: from package.json or "skills-marketplace")
  --owner <name>        Owner name (default: from package.json author or "Skills Team")
  --email <email>       Owner email (optional)
  --description <desc>  Marketplace description
  --output <path>       Output path (default: .claude-plugin/marketplace.json)
  --skills-dir <path>   Skills directory (default: skills)
  --help                Show this help message
`);
        process.exit(0);
    }
  }

  return options;
}

// Parse YAML frontmatter from SKILL.md
function parseFrontmatter(content) {
  const frontmatterRegex = /^---\n([\s\S]*?)\n---/;
  const match = content.match(frontmatterRegex);

  if (!match) {
    return {};
  }

  const frontmatter = {};
  const lines = match[1].split('\n');

  for (const line of lines) {
    const colonIndex = line.indexOf(':');
    if (colonIndex > 0) {
      const key = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      frontmatter[key] = value;
    }
  }

  return frontmatter;
}

// Scan skills directory and collect skill metadata
function scanSkills(skillsDir) {
  const skills = [];
  const rootDir = process.cwd();
  const fullSkillsDir = path.resolve(rootDir, skillsDir);

  if (!fs.existsSync(fullSkillsDir)) {
    console.error(`Skills directory not found: ${fullSkillsDir}`);
    process.exit(1);
  }

  const entries = fs.readdirSync(fullSkillsDir, { withFileTypes: true });

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;

    const skillDir = path.join(fullSkillsDir, entry.name);
    const skillMdPath = path.join(skillDir, 'SKILL.md');

    if (!fs.existsSync(skillMdPath)) {
      console.warn(`Warning: No SKILL.md found in ${entry.name}, skipping...`);
      continue;
    }

    const content = fs.readFileSync(skillMdPath, 'utf-8');
    const frontmatter = parseFrontmatter(content);

    const skill = {
      name: frontmatter.name || entry.name,
      source: `./${skillsDir}/${entry.name}`,
      description: frontmatter.description || `Skill: ${entry.name}`,
      strict: false, // Plugin doesn't need its own plugin.json; marketplace entry defines everything
    };

    // Add optional fields if present
    if (frontmatter.version) {
      skill.version = frontmatter.version;
    }
    if (frontmatter.author) {
      skill.author = { name: frontmatter.author };
    }
    if (frontmatter.keywords) {
      skill.keywords = frontmatter.keywords.split(',').map(k => k.trim());
    }
    if (frontmatter.category) {
      skill.category = frontmatter.category;
    }

    skills.push(skill);
    console.log(`Found skill: ${skill.name}`);
  }

  return skills;
}

// Try to read defaults from package.json if it exists
function getDefaults() {
  const defaults = {
    name: 'skills-marketplace',
    owner: 'Skills Team',
    description: 'A collection of Claude Code skills',
  };

  const packageJsonPath = path.join(process.cwd(), 'package.json');
  if (fs.existsSync(packageJsonPath)) {
    try {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8'));
      if (pkg.name) {
        defaults.name = pkg.name.replace(/[^a-z0-9-]/gi, '-').toLowerCase();
      }
      if (pkg.author) {
        if (typeof pkg.author === 'string') {
          defaults.owner = pkg.author;
        } else if (pkg.author.name) {
          defaults.owner = pkg.author.name;
          if (pkg.author.email) {
            defaults.email = pkg.author.email;
          }
        }
      }
      if (pkg.description) {
        defaults.description = pkg.description;
      }
    } catch (e) {
      // Ignore parse errors
    }
  }

  return defaults;
}

// Generate the marketplace.json
function generateMarketplace(options) {
  const defaults = getDefaults();
  const skills = scanSkills(options.skillsDir);

  if (skills.length === 0) {
    console.error('No skills found. Make sure your skills directory contains subdirectories with SKILL.md files.');
    process.exit(1);
  }

  const marketplace = {
    name: options.name || defaults.name,
    owner: {
      name: options.owner || defaults.owner,
    },
    metadata: {
      description: options.description || defaults.description,
      pluginRoot: `./${options.skillsDir}`,
    },
    plugins: skills,
  };

  // Add email if provided
  if (options.email || defaults.email) {
    marketplace.owner.email = options.email || defaults.email;
  }

  return marketplace;
}

// Write marketplace.json to file
function writeMarketplace(marketplace, outputPath) {
  const fullPath = path.resolve(process.cwd(), outputPath);
  const dir = path.dirname(fullPath);

  // Create directory if it doesn't exist
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  fs.writeFileSync(fullPath, JSON.stringify(marketplace, null, 2) + '\n');
  console.log(`\nGenerated marketplace.json at: ${fullPath}`);
  console.log(`Total plugins: ${marketplace.plugins.length}`);
}

// Main
function main() {
  const options = parseArgs();
  const marketplace = generateMarketplace(options);
  writeMarketplace(marketplace, options.output);
}

main();
